import os
import logging

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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

PRODUCT_NAME = "Digital Product"
PRICE_PER_ITEM = 50
QUANTITIES = [1, 5, 10]
MAX_QUANTITY = 1000


def is_admin(update: Update) -> bool:
    return (
        ADMIN_ID != 0
        and update.effective_user is not None
        and update.effective_user.id == ADMIN_ID
    )


def main_menu(admin=False):
    keyboard = [
        [
            InlineKeyboardButton(
                "🛒 Buy",
                callback_data="buy"
            )
        ]
    ]

    if admin:
        keyboard.append([
            InlineKeyboardButton(
                "💰 Balance",
                callback_data="admin_balance"
            ),
            InlineKeyboardButton(
                "📊 Transactions",
                callback_data="admin_transactions"
            ),
        ])

    return InlineKeyboardMarkup(keyboard)


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    context.user_data.pop("awaiting_custom_quantity", None)

    await update.message.reply_text(
        "Welcome to Buy More Accounts! 🛒\n\n"
        "Purchase digital products securely below.",
        reply_markup=main_menu(is_admin(update))
    )


async def balance_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not is_admin(update):
        await update.message.reply_text("Access denied.")
        return

    try:
        balance = await context.bot.get_my_star_balance()

        await update.message.reply_text(
            f"💰 Your bot's Stars balance: {balance} ⭐"
        )
    except Exception:
        logger.exception("Stars balance request failed")
        await update.message.reply_text(
            "Could not retrieve your Stars balance. "
            "Please check the Render logs."
        )


async def transactions_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not is_admin(update):
        await update.message.reply_text("Access denied.")
        return

    try:
        result = await context.bot.get_star_transactions(
            offset=0,
            limit=10
        )

        transactions = result.transactions

        if not transactions:
            await update.message.reply_text(
                "📊 No Stars transactions were returned."
            )
            return

        lines = ["📊 Recent Stars transactions:\n"]

        for transaction in transactions:
            lines.append(
                f"Amount: {transaction.amount} ⭐\n"
                f"Date: {transaction.date}\n"
                f"Transaction ID: {transaction.id}\n"
            )

        await update.message.reply_text("\n".join(lines))

    except Exception:
        logger.exception("Stars transaction request failed")
        await update.message.reply_text(
            "Could not retrieve transactions. "
            "Please check the Render logs."
        )


async def buttons(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    if query.data == "buy":
        keyboard = [
            [
                InlineKeyboardButton(
                    f"{q} item(s) — {q * PRICE_PER_ITEM} ⭐",
                    callback_data=f"quantity:{q}"
                )
            ]
            for q in QUANTITIES
        ]

        keyboard.append([
            InlineKeyboardButton(
                "✏️ Custom quantity",
                callback_data="custom_quantity"
            )
        ])

        await query.edit_message_text(
            f"Select quantity of {PRODUCT_NAME}:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == "custom_quantity":
        context.user_data["awaiting_custom_quantity"] = True

        await query.message.reply_text(
            f"Enter the quantity you want (1–{MAX_QUANTITY}).\n"
            f"Price per item: {PRICE_PER_ITEM} Stars."
        )

    elif query.data.startswith("quantity:"):
        try:
            quantity = int(query.data.split(":")[1])
        except (ValueError, IndexError):
            await query.message.reply_text("Invalid quantity.")
            return

        await send_order_invoice(
            update, context, quantity,
            query.message.chat_id
        )

    elif query.data == "admin_balance":
        if not is_admin(update):
            await query.answer("Access denied.", show_alert=True)
            return

        try:
            balance = await context.bot.get_my_star_balance()
            await query.message.reply_text(
                f"💰 Bot Stars balance: {balance} ⭐"
            )
        except Exception:
            logger.exception("Stars balance request failed")
            await query.message.reply_text(
                "Could not retrieve the Stars balance."
            )

    elif query.data == "admin_transactions":
        if not is_admin(update):
            await query.answer("Access denied.", show_alert=True)
            return

        await transactions_command_from_button(
            update, context
        )


async def transactions_command_from_button(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    try:
        result = await context.bot.get_star_transactions(
            offset=0,
            limit=10
        )

        transactions = result.transactions

        if not transactions:
            await update.callback_query.message.reply_text(
                "📊 No Stars transactions were returned."
            )
            return

        lines = ["📊 Recent Stars transactions:\n"]

        for transaction in transactions:
            lines.append(
                f"Amount: {transaction.amount} ⭐\n"
                f"Date: {transaction.date}\n"
                f"Transaction ID: {transaction.id}\n"
            )

        await update.callback_query.message.reply_text(
            "\n".join(lines)
        )

    except Exception:
        logger.exception("Stars transaction request failed")
        await update.callback_query.message.reply_text(
            "Could not retrieve transactions."
        )


async def custom_quantity_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not context.user_data.get("awaiting_custom_quantity"):
        return

    try:
        quantity = int(update.message.text.strip())
    except (ValueError, AttributeError):
        await update.message.reply_text(
            "Please enter a whole number, such as 3 or 20."
        )
        return

    if not 1 <= quantity <= MAX_QUANTITY:
        await update.message.reply_text(
            f"Enter a quantity between 1 and {MAX_QUANTITY}."
        )
        return

    context.user_data.pop("awaiting_custom_quantity", None)

    await send_order_invoice(
        update,
        context,
        quantity,
        update.effective_chat.id
    )


async def send_order_invoice(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    quantity: int,
    chat_id: int
):
    if not 1 <= quantity <= MAX_QUANTITY:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Invalid quantity."
        )
        return

    total = quantity * PRICE_PER_ITEM

    await context.bot.send_invoice(
        chat_id=chat_id,
        title=PRODUCT_NAME,
        description=f"{quantity} digital product(s)",
        payload=f"digital_product:{quantity}",
        currency="XTR",
        prices=[LabeledPrice(PRODUCT_NAME, total)],
        provider_token=""
    )


async def precheckout(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.pre_checkout_query

    try:
        prefix, quantity_text = query.invoice_payload.split(":", 1)
        quantity = int(quantity_text)
    except (ValueError, AttributeError):
        await query.answer(
            ok=False,
            error_message="Invalid order. Please try again."
        )
        return

    if (
        prefix != "digital_product"
        or not 1 <= quantity <= MAX_QUANTITY
        or query.currency != "XTR"
        or query.total_amount != quantity * PRICE_PER_ITEM
    ):
        await query.answer(
            ok=False,
            error_message="Invalid order amount."
        )
        return

    await query.answer(ok=True)


async def successful_payment(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    payment = update.message.successful_payment

    if payment.currency != "XTR":
        await update.message.reply_text(
            "Payment currency could not be verified. "
            "Please contact support."
        )
        return

    try:
        prefix, quantity_text = payment.invoice_payload.split(":", 1)
        quantity = int(quantity_text)
    except (ValueError, AttributeError):
        await update.message.reply_text(
            "Payment received, but the order details need review."
        )
        return

    if (
        prefix != "digital_product"
        or not 1 <= quantity <= MAX_QUANTITY
        or payment.total_amount != quantity * PRICE_PER_ITEM
    ):
        await update.message.reply_text(
            "Payment received, but the order needs admin review."
        )
        return

    await update.message.reply_text(
        "✅ Payment successful!\n\n"
        f"Product: {PRODUCT_NAME}\n"
        f"Quantity: {quantity}\n"
        f"Paid: {payment.total_amount} ⭐\n\n"
        "Thank you for your purchase!\n"
        "Please follow the seller's delivery instructions."
    )

    if ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "🆕 New paid order\n"
                    f"Customer ID: {update.effective_user.id}\n"
                    f"Product: {PRODUCT_NAME}\n"
                    f"Quantity: {quantity}\n"
                    f"Amount: {payment.total_amount} Stars\n"
                    f"Payment ID: "
                    f"{payment.telegram_payment_charge_id}"
                )
            )
        except Exception:
            logger.exception("Admin payment notification failed")


def main():
    if not TOKEN:
        raise RuntimeError(
            "BOT_TOKEN environment variable is missing."
        )

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(
        CommandHandler("transactions", transactions_command)
    )

    app.add_handler(CallbackQueryHandler(buttons))

    app.add_handler(PreCheckoutQueryHandler(precheckout))

    app.add_handler(
        MessageHandler(
            filters.SUCCESSFUL_PAYMENT,
            successful_payment
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            custom_quantity_message
        )
    )

    app.run_polling()


if __name__ == "__main__":
    main()
