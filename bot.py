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

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

PRODUCT_NAME = "Digital Product"
PRICE_PER_ITEM = 50
QUANTITIES = [1, 5, 10]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[
        InlineKeyboardButton(
            "🛒 Buy Digital Products",
            callback_data="buy"
        )
    ]]

    await update.message.reply_text(
        "Welcome to Buy More Accounts!\n\n"
        "Purchase digital products securely below.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

        await query.edit_message_text(
            f"Select quantity of {PRODUCT_NAME}:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data.startswith("quantity:"):
        quantity = int(query.data.split(":")[1])

        if quantity not in QUANTITIES:
            await query.edit_message_text("Invalid quantity.")
            return

        total = quantity * PRICE_PER_ITEM

        await context.bot.send_invoice(
            chat_id=query.message.chat_id,
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

    if not query.invoice_payload.startswith("digital_product:"):
        await query.answer(
            ok=False,
            error_message="Invalid order. Please try again."
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
            "Payment currency could not be verified. Contact support."
        )
        return

    quantity = int(payment.invoice_payload.split(":")[1])

    await update.message.reply_text(
        "✅ Payment successful!\n\n"
        f"Product: {PRODUCT_NAME}\n"
        f"Quantity: {quantity}\n"
        f"Paid: {payment.total_amount} ⭐\n\n"
        "Thank you for your purchase!\n"
        "Your order has been recorded. "
        "Please follow the seller's delivery instructions."
    )

    if ADMIN_ID:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                "New paid order\n"
                f"Customer ID: {update.effective_user.id}\n"
                f"Product: {PRODUCT_NAME}\n"
                f"Quantity: {quantity}\n"
                f"Amount: {payment.total_amount} Stars\n"
                f"Payment ID: {payment.telegram_payment_charge_id}"
            )
        )


def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is missing.")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(
        MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment)
    )

    app.run_polling()


if __name__ == "__main__":
    main()
