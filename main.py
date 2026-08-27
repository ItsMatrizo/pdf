import os
import io
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
import pypdfium2 as pdfium
from pypdf import PdfReader

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
        file = await context.bot.get_file(document.file_id)
        file_bytes = await file.download_as_bytearray()

        # Get page count using pypdf (fast, pure Python)
        reader = PdfReader(io.BytesIO(file_bytes))
        total_pages = len(reader.pages)

        # Store for later use
        user_id = update.effective_user.id
        user_pdf_data[user_id] = {
            "bytes": file_bytes,
            "total_pages": total_pages
        }

        await update.message.reply_text(f"📄 Total pages: **{total_pages}**")

        # Convert first 5 pages to images (or fewer)
        pages_to_send = min(5, total_pages)
        if pages_to_send == 0:
            await update.message.reply_text("This PDF has no pages.")
            return

        # Render with pypdfium2
        pdf = pdfium.PdfDocument(io.BytesIO(file_bytes))
        for page_num in range(pages_to_send):
            page = pdf.get_page(page_num)
            # Render at 150 DPI
            bitmap = page.render(scale=150/72)  # 72 is default DPI, so 150/72 = 2.0833
            pil_image = bitmap.to_pil()
            img_bytes = io.BytesIO()
            pil_image.save(img_bytes, format="PNG")
            img_bytes.seek(0)
            await update.message.reply_photo(
                photo=img_bytes,
                caption=f"Page {page_num + 1} / {total_pages}"
            )
        pdf.close()

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
    if start < 1 or end > total_pages or start > end:
        await update.message.reply_text(
            f"Invalid range. Pages are 1‑{total_pages} and start ≤ end."
        )
        return

    try:
        pdf_bytes = user_pdf_data[user_id]["bytes"]
        pdf = pdfium.PdfDocument(io.BytesIO(pdf_bytes))
        for page_num in range(start - 1, end):
            page = pdf.get_page(page_num)
            bitmap = page.render(scale=150/72)
            pil_image = bitmap.to_pil()
            img_bytes = io.BytesIO()
            pil_image.save(img_bytes, format="PNG")
            img_bytes.seek(0)
            await update.message.reply_photo(
                photo=img_bytes,
                caption=f"Page {page_num + 1} / {total_pages}"
            )
        pdf.close()
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

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pages", pages_command))
    app.add_handler(CommandHandler("done", done_command))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_pdf))

    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
