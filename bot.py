import os
import logging
import asyncio
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    PreCheckoutQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PORT = int(os.getenv("PORT", "10000"))

PRICE_PER_ITEM = 50
MAX_QUANTITY = 1000

# Basic in-memory order tracking.
# Orders are lost when the process restarts.
ORDERS = {}
NEXT_ORDER_ID = 1


# --------------------------------------------------
# WEB SERVER: REQUIRED BY RENDER WEB SERVICES
# --------------------------------------------------

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path

        if path in ("/", "/health"):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"GrabAccounts bot is running.")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        return


def start_web_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    logger.info("Health server listening on port %s", PORT)
    server.serve_forever()


# --------------------------------------------------
# ADMIN ACCESS
# --------------------------------------------------

def is_admin(update):
    return (
        ADMIN_ID != 0
        and update.effective_user is not None
        and update.effective_user.id == ADMIN_ID
    )


def main_menu(admin=False):
    keyboard = [
        [InlineKeyboardButton("🛒 Buy", callback_data="buy")]
    ]

    if admin:
        keyboard.append([
            InlineKeyboardButton(
                "💰 Balance",
                callback_data="balance",
            ),
            InlineKeyboardButton(
                "📊 Transactions",
                callback_data="transactions",
            ),
        ])

    return InlineKeyboardMarkup(keyboard)


# --------------------------------------------------
# START
# --------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("awaiting_quantity", None)
    context.user_data.pop("reply_order_id", None)

    await update.message.reply_text(
        "Welcome to GrabAccounts! 🛍️\n\n"
        "Buy digital products using Telegram Stars.",
        reply_markup=main_menu(is_admin(update)),
    )


# --------------------------------------------------
# STARS BALANCE
# --------------------------------------------------

async def show_balance(update, context):
    if not is_admin(update):
        if update.callback_query:
            await update.callback_query.answer(
                "Admin only.",
                show_alert=True,
            )
        return

    try:
        result = await context.bot.get_my_star_balance()

        amount = getattr(result, "amount", result)

        message = f"💰 Bot Stars balance: {amount} ⭐"

        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.reply_text(message)
        else:
            await update.message.reply_text(message)

    except Exception:
        logger.exception("Could not retrieve Stars balance")

        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.reply_text(
                "Unable to retrieve the Stars balance."
            )
        else:
            await update.message.reply_text(
                "Unable to retrieve the Stars balance."
            )


# --------------------------------------------------
# TRANSACTIONS
# --------------------------------------------------

async def show_transactions(update, context):
    if not is_admin(update):
        if update.callback_query:
            await update.callback_query.answer(
                "Admin only.",
                show_alert=True,
            )
        return

    try:
        result = await context.bot.get_star_transactions(
            offset=0,
            limit=10,
        )

        transactions = result.transactions

        if not transactions:
            message = "No Stars transactions were returned."
        else:
            lines = ["📊 Recent Stars transactions:\n"]

            for item in transactions:
                lines.append(
                    f"Amount: {item.amount} ⭐\n"
                    f"Date: {item.date}\n"
                    f"Transaction ID: {item.id}\n"
                )

            message = "\n".join(lines)

        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.reply_text(message)
        else:
            await update.message.reply_text(message)

    except Exception:
        logger.exception("Could not retrieve Stars transactions")

        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.reply_text(
                "Unable to retrieve transactions."
            )
        else:
            await update.message.reply_text(
                "Unable to retrieve transactions."
            )


# --------------------------------------------------
# BUY AND QUANTITY SELECTION
# --------------------------------------------------

async def show_buy_menu(query):
    keyboard = [
        [
            InlineKeyboardButton(
                f"{quantity} item(s) — "
                f"{quantity * PRICE_PER_ITEM} ⭐",
                callback_data=f"quantity:{quantity}",
            )
        ]
        for quantity in (1, 5, 10)
    ]

    keyboard.append([
        InlineKeyboardButton(
            "✏️ Custom quantity",
            callback_data="custom",
        )
    ])

    await query.edit_message_text(
        f"Select your quantity.\n"
        f"Price per item: {PRICE_PER_ITEM} Stars.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def send_invoice(update, context, quantity, chat_id):
    total = quantity * PRICE_PER_ITEM

    await context.bot.send_invoice(
        chat_id=chat_id,
        title="Digital Products",
        description=f"Purchase of {quantity} digital item(s).",
        payload=f"grabaccounts:{quantity}",
        currency="XTR",
        prices=[
            LabeledPrice("Digital Products", total)
        ],
        provider_token="",
    )


# --------------------------------------------------
# BUTTON HANDLER
# --------------------------------------------------

async def buttons(update, context):
    query = update.callback_query
    data = query.data

    if data == "balance":
        await show_balance(update, context)
        return

    if data == "transactions":
        await show_transactions(update, context)
        return

    if data == "buy":
        await query.answer()
        await show_buy_menu(query)
        return

    if data == "custom":
        await query.answer()
        context.user_data["awaiting_quantity"] = True

        await query.message.reply_text(
            f"Enter a quantity between 1 and {MAX_QUANTITY}."
        )
        return

    if data.startswith("quantity:"):
        await query.answer()

        try:
            quantity = int(data.split(":", 1)[1])
        except ValueError:
            await query.message.reply_text("Invalid quantity.")
            return

        if not 1 <= quantity <= MAX_QUANTITY:
            await query.message.reply_text("Invalid quantity.")
            return

        await send_invoice(
            update,
            context,
            quantity,
            query.message.chat_id,
        )
        return

    if data.startswith("reply:"):
        if not is_admin(update):
            await query.answer("Admin only.", show_alert=True)
            return

        await query.answer()

        try:
            order_id = int(data.split(":", 1)[1])
            order = ORDERS[order_id]
        except (ValueError, KeyError):
            await query.message.reply_text(
                "Order not found. It may have been lost after a restart."
            )
            return

        context.user_data["reply_order_id"] = order_id

        await query.message.reply_text(
            f"Type your message for customer "
            f"{order['customer_id']}.\n\n"
            "Send /cancel to cancel your reply."
        )
        return

    if data.startswith("delivered:"):
        if not is_admin(update):
            await query.answer("Admin only.", show_alert=True)
            return

        await query.answer()

        try:
            order_id = int(data.split(":", 1)[1])
            order = ORDERS[order_id]
        except (ValueError, KeyError):
            await query.message.reply_text(
                "Order not found. Check the order notification."
            )
            return

        order["status"] = "Delivered"

        await query.message.reply_text(
            f"✅ Order #{order_id} marked as delivered."
        )

        try:
            await context.bot.send_message(
                chat_id=order["customer_id"],
                text=f"✅ Your order #{order_id} has been marked as delivered.",
            )
        except Exception:
            logger.exception("Could not notify customer of delivery")

        return


# --------------------------------------------------
# CUSTOM QUANTITY AND ADMIN REPLIES
# --------------------------------------------------

async def text_messages(update, context):
    global NEXT_ORDER_ID

    user_id = update.effective_user.id
    text = update.message.text.strip()

    if text == "/cancel" and is_admin(update):
        context.user_data.pop("reply_order_id", None)
        await update.message.reply_text("Reply cancelled.")
        return

    # Admin replies to customers.
    reply_order_id = context.user_data.get("reply_order_id")

    if is_admin(update) and reply_order_id is not None:
        order = ORDERS.get(reply_order_id)

        if not order:
            context.user_data.pop("reply_order_id", None)
            await update.message.reply_text("Order not found.")
            return

        try:
            await context.bot.send_message(
                chat_id=order["customer_id"],
                text=f"📩 Message from GrabAccounts support:\n\n{text}",
            )

            await update.message.reply_text(
                f"✅ Message sent to customer "
                f"{order['customer_id']}."
            )

        except Exception:
            logger.exception("Failed to send admin reply")

            await update.message.reply_text(
                "Could not send the message. "
                "The customer may not have started the bot."
            )

        context.user_data.pop("reply_order_id", None)
        return

    # Custom quantity.
    if context.user_data.get("awaiting_quantity"):
        try:
            quantity = int(text)
        except ValueError:
            await update.message.reply_text(
                "Enter a whole number, such as 2 or 15."
            )
            return

        if not 1 <= quantity <= MAX_QUANTITY:
            await update.message.reply_text(
                f"Enter a number between 1 and {MAX_QUANTITY}."
            )
            return

        context.user_data.pop("awaiting_quantity", None)

        await send_invoice(
            update,
            context,
            quantity,
            update.effective_chat.id,
        )


# --------------------------------------------------
# PAYMENT VALIDATION
# --------------------------------------------------

async def precheckout(update, context):
    query = update.pre_checkout_query

    try:
        prefix, quantity_text = query.invoice_payload.split(":", 1)
        quantity = int(quantity_text)
    except (ValueError, AttributeError):
        await query.answer(
            ok=False,
            error_message="Invalid order.",
        )
        return

    if (
        prefix != "grabaccounts"
        or not 1 <= quantity <= MAX_QUANTITY
        or query.currency != "XTR"
        or query.total_amount != quantity * PRICE_PER_ITEM
    ):
        await query.answer(
            ok=False,
            error_message="Invalid payment amount.",
        )
        return

    await query.answer(ok=True)


# --------------------------------------------------
# SUCCESSFUL PAYMENT AND ADMIN NOTIFICATION
# --------------------------------------------------

async def successful_payment(update, context):
    global NEXT_ORDER_ID

    payment = update.message.successful_payment
    customer_id = update.effective_user.id

    try:
        prefix, quantity_text = payment.invoice_payload.split(":", 1)
        quantity = int(quantity_text)
    except (ValueError, AttributeError):
        await update.message.reply_text(
            "Payment received. Please contact support to verify your order."
        )
        return

    if (
        prefix != "grabaccounts"
        or payment.currency != "XTR"
        or not 1 <= quantity <= MAX_QUANTITY
        or payment.total_amount != quantity * PRICE_PER_ITEM
    ):
        await update.message.reply_text(
            "Payment received, but the order needs verification."
        )
        return

    # Avoid processing the same charge twice in this running process.
    for existing in ORDERS.values():
        if (
            existing["payment_id"]
            == payment.telegram_payment_charge_id
        ):
            await update.message.reply_text(
                "This payment has already been recorded."
            )
            return

    order_id = NEXT_ORDER_ID
    NEXT_ORDER_ID += 1

    ORDERS[order_id] = {
        "customer_id": customer_id,
        "quantity": quantity,
        "amount": payment.total_amount,
        "payment_id": payment.telegram_payment_charge_id,
        "status": "Awaiting delivery",
    }

    await update.message.reply_text(
        "✅ Payment successful!\n\n"
        f"Order: #{order_id}\n"
        f"Quantity: {quantity}\n"
        f"Paid: {payment.total_amount} ⭐\n\n"
        "Your order has been received. "
        "We will arrange delivery."
    )

    if ADMIN_ID:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "💬 Reply to Customer",
                    callback_data=f"reply:{order_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "✅ Mark as Delivered",
                    callback_data=f"delivered:{order_id}",
                )
            ],
        ])

        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"🆕 NEW PAID ORDER #{order_id}\n\n"
                    f"Customer ID: {customer_id}\n"
                    f"Quantity: {quantity}\n"
                    f"Amount: {payment.total_amount} Stars\n"
                    f"Payment ID: "
                    f"{payment.telegram_payment_charge_id}\n"
                    "Status: Awaiting delivery"
                ),
                reply_markup=keyboard,
            )

        except Exception:
            logger.exception("Admin notification failed")


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN is missing.")

    # Start the HTTP server in a separate thread.
    threading.Thread(
        target=start_web_server,
        daemon=True,
    ).start()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", show_balance))
    app.add_handler(CommandHandler("transactions", show_transactions))
    app.add_handler(CommandHandler("cancel", start))

    app.add_handler(CallbackQueryHandler(buttons))

    app.add_handler(PreCheckoutQueryHandler(precheckout))

    app.add_handler(
        MessageHandler(
            filters.SUCCESSFUL_PAYMENT,
            successful_payment,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_messages,
        )
    )

    app.run_polling()


if __name__ == "__main__":
    main()
