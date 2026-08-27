import os
import io
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
import fitz  # PyMuPDF

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Allowed user ID (only you)
ALLOWED_USER_ID = 7747769628

# In‑memory storage: user_id -> {"bytes": pdf_bytes, "total_pages": int}
user_pdf_data = {}

async def check_user(update: Update) -> bool:
    """Returns True if the user is allowed, otherwise replies and returns False."""
    if update.effective_user.id != ALLOWED_USER_ID:
        await update.message.reply_text("⛔ Unauthorized. This bot is private.")
        return False
    return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user(update):
        return
    await update.message.reply_text(
        "👋 Send me a PDF file and I'll:\n"
        "• count all pages\n"
        "• send the first 5 pages as pictures\n\n"
        "Then use:\n"
        "/pages <start> <end> – get a custom page range (1‑indexed)\n"
        "/done – clear the stored PDF from memory"
    )

async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user(update):
        return

    document = update.message.document
    if document.mime_type != 'application/pdf':
        await update.message.reply_text("Please send a PDF file.")
        return

    await update.message.reply_text("⏳ Processing PDF...")

    try:
        # Download file as bytes
        file = await context.bot.get_file(document.file_id)
        file_bytes = await file.download_as_bytearray()

        # Open PDF with PyMuPDF to get page count
        pdf_document = fitz.open(stream=file_bytes, filetype="pdf")
        total_pages = pdf_document.page_count
        pdf_document.close()

        # Store the bytes and page count for later use
        user_id = update.effective_user.id
        user_pdf_data[user_id] = {
            "bytes": file_bytes,
            "total_pages": total_pages
        }

        await update.message.reply_text(f"📄 Total pages: **{total_pages}**")

        # Send first 5 pages (or fewer)
        pages_to_send = min(5, total_pages)
        if pages_to_send == 0:
            await update.message.reply_text("This PDF has no pages.")
            return

        # Re‑open the PDF from stored bytes
        pdf_document = fitz.open(stream=file_bytes, filetype="pdf")
        for page_num in range(pages_to_send):
            page = pdf_document.load_page(page_num)
            pix = page.get_pixmap(dpi=150)
            img_bytes = pix.tobytes("png")
            await update.message.reply_photo(
                photo=io.BytesIO(img_bytes),
                caption=f"Page {page_num + 1} / {total_pages}"
            )
        pdf_document.close()

        if total_pages > 5:
            await update.message.reply_text(
                "ℹ️ Only the first 5 pages are shown. "
                "Use /pages <start> <end> to get a custom range."
            )

    except Exception as e:
        logger.error(f"PDF processing error: {e}")
        await update.message.reply_text(
            "❌ Sorry, I couldn't process that PDF. Please try another file."
        )

async def pages_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user(update):
        return

    user_id = update.effective_user.id
    if user_id not in user_pdf_data:
        await update.message.reply_text("❌ No PDF stored. Please send a PDF first.")
        return

    # Parse arguments: /pages start end
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("Usage: /pages <start> <end>\nExample: /pages 3 7")
        return

    try:
        start = int(args[0])
        end = int(args[1])
    except ValueError:
        await update.message.reply_text("Please provide valid integers.")
        return

    total_pages = user_pdf_data[user_id]["total_pages"]
    # Convert to 0‑based and clamp to valid range
    if start < 1 or end > total_pages or start > end:
        await update.message.reply_text(
            f"Invalid range. Pages are 1‑{total_pages} and start ≤ end."
        )
        return

    try:
        pdf_bytes = user_pdf_data[user_id]["bytes"]
        pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
        for page_num in range(start - 1, end):  # 0‑based
            page = pdf_document.load_page(page_num)
            pix = page.get_pixmap(dpi=150)
            img_bytes = pix.tobytes("png")
            await update.message.reply_photo(
                photo=io.BytesIO(img_bytes),
                caption=f"Page {page_num + 1} / {total_pages}"
            )
        pdf_document.close()
    except Exception as e:
        logger.error(f"Pages command error: {e}")
        await update.message.reply_text("❌ Error extracting pages. Please try again.")

async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user(update):
        return

    user_id = update.effective_user.id
    if user_id in user_pdf_data:
        del user_pdf_data[user_id]
        await update.message.reply_text("🗑️ PDF data cleared from memory.")
    else:
        await update.message.reply_text("No PDF data to clear.")

def main():
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_TOKEN environment variable not set")

    app = Application.builder().token(token).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pages", pages_command))
    app.add_handler(CommandHandler("done", done_command))

    # PDF document handler
    app.add_handler(MessageHandler(filters.Document.ALL, handle_pdf))

    # Start polling (keeps the bot alive)
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
