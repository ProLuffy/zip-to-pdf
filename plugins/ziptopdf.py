import re
import os
import zipfile
import tempfile
import asyncio
import shutil
from PIL import Image
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from config import ADMIN_IDS, MONGO_URI, DB_NAME, SUPPORT_CHAT

# MongoDB Setup
mongo_client = MongoClient(MONGO_URI)
db = mongo_client[DB_NAME]
autho_users_collection = db["authorized_users"]
user_settings_collection = db["user_settings"]

# Utility Functions
def natural_sort(file_list):
    """Sorts file names naturally (e.g., img1, img2, img10)."""
    return sorted(file_list, key=lambda f: [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', f)])

def remove_duplicates(file_list):
    """Keep base image (e.g., 1.jpg) and remove variants like 1t.jpg."""
    base_map = {}
    valid_extensions = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff", ".img")
    for file in file_list:
        name, ext = os.path.splitext(os.path.basename(file))
        if ext.lower() not in valid_extensions:
            continue
        match = re.match(r"^(\d+)[a-zA-Z]?$", name)
        if match:
            base = match.group(1)
            if base not in base_map or not name.endswith("t"):
                base_map[base] = file
    return list(base_map.values())

def generate_pdf(image_files, output_path):
    """Convert images to PDF without compression."""
    image_iter = (Image.open(f).convert("RGB") for f in image_files)
    first = next(image_iter)
    first.save(output_path, save_all=True, append_images=image_iter)

# MongoDB Helper Functions
async def add_autho_user(user_id: int):
    """Add an authorized user to MongoDB."""
    autho_users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id}},
        upsert=True
    )

async def remove_autho_user(user_id: int):
    """Remove an authorized user from MongoDB."""
    autho_users_collection.delete_one({"user_id": user_id})

async def is_autho_user_exist(user_id: int) -> bool:
    """Check if a user is authorized."""
    return bool(autho_users_collection.find_one({"user_id": user_id}))

async def get_all_autho_users() -> list:
    """Get list of all authorized users."""
    return [doc["user_id"] for doc in autho_users_collection.find()]

async def get_format_template(user_id: int) -> str:
    """Get format template for a user (default if not set)."""
    user = user_settings_collection.find_one({"user_id": user_id})
    return user.get("format_template", "default_format") if user else "default_format"

async def get_media_preference(user_id: int) -> str:
    """Get media preference for a user (default if not set)."""
    user = user_settings_collection.find_one({"user_id": user_id})
    return user.get("media_preference", "default") if user else "default"

# Command Handlers
@Client.on_message(filters.private & filters.command("addautho_user") & filters.user(ADMIN_IDS))
async def add_authorise_user(client: Client, message: Message):
    ids = message.text.removeprefix("/addautho_user").strip().split()
    check = True

    try:
        if ids:
            for id_str in ids:
                if len(id_str) == 10 and id_str.isdigit():
                    await add_autho_user(int(id_str))
                else:
                    check = False
                    break
        else:
            check = False
    except ValueError:
        check = False

    if check:
        await message.reply_text(
            f'**Authorised Users Added ✅**\n<blockquote>`{" ".join(ids)}`</blockquote>',
            parse_mode="html"
        )
    else:
        await message.reply_text(
            "**INVALID USE OF COMMAND:**\n"
            "<blockquote>**➪ Check if the command is empty OR the added ID should be correct (10 digit numbers)**</blockquote>",
            parse_mode="html"
        )

@Client.on_message(filters.private & filters.command("delautho_user") & filters.user(ADMIN_IDS))
async def delete_authorise_user(client: Client, message: Message):
    ids = message.text.removeprefix("/delautho_user").strip().split()
    check = True

    try:
        if ids:
            for id_str in ids:
                if len(id_str) == 10 and id_str.isdigit():
                    await remove_autho_user(int(id_str))
                else:
                    check = False
                    break
        else:
            check = False
    except ValueError:
        check = False

    if check:
        await message.reply_text(
            f'**Deleted Authorised Users 🆑**\n<blockquote>`{" ".join(ids)}`</blockquote>',
            parse_mode="html"
        )
    else:
        await message.reply_text(
            "**INVALID USE OF COMMAND:**\n"
            "<blockquote>**➪ Check if the command is empty OR the added ID should be correct (10 digit numbers)**</blockquote>",
            parse_mode="html"
        )

@Client.on_message(filters.private & filters.command("autho_users") & filters.user(ADMIN_IDS))
async def authorise_user_list(client: Client, message: Message):
    autho_users = await get_all_autho_users()
    if autho_users:
        autho_users_str = "\n".join(map(str, autho_users))
        await message.reply_text(
            f"🚻 **AUTHORIZED USERS:** 🌀\n\n`{autho_users_str}`",
            parse_mode="html"
        )
    else:
        await message.reply_text("No authorized users found.", parse_mode="html")

@Client.on_message(filters.private & filters.command("check_autho"))
async def check_authorise_user(client: Client, message: Message):
    user_id = message.from_user.id
    check = await is_autho_user_exist(user_id)
    if check:
        await message.reply_text(
            "**Yes, You are an Authorised user 🟢**\n"
            "<blockquote>You can send files to Rename or Convert to PDF.</blockquote>",
            parse_mode="html"
        )
    else:
        await message.reply_text(
            f"**Nope, You are not an Authorised user 🔴**\n"
            f"<blockquote>You can't send files to Rename or Convert to PDF.</blockquote>\n"
            f"**Contact {SUPPORT_CHAT} to get authorized.**",
            parse_mode="html"
        )

@Client.on_message(filters.private & (filters.document | filters.video | filters.audio))
async def auto_rename_files(client: Client, message: Message):
    user_id = message.from_user.id
    check = await is_autho_user_exist(user_id)
    if not check:
        await message.reply_text(
            f"<b>⚠️ You are not an Authorised User ⚠️</b>\n"
            f"<blockquote>If you want to use this bot, please contact: {SUPPORT_CHAT}</blockquote>",
            parse_mode="html"
        )
        return

    # Add inline buttons for Zip to PDF and Close
    inline_buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("Zip to PDF 📄", callback_data=f"convert_pdf_{message.message_id}")],
        [InlineKeyboardButton("Close ❌", callback_data="close")]
    ])

    await message.reply_text(
        "File received! Choose an option below:",
        reply_markup=inline_buttons,
        parse_mode="html"
    )

@Client.on_callback_query(filters.regex(r"convert_pdf_(\d+)"))
async def handle_convert_pdf_callback(client: Client, callback_query):
    user_id = callback_query.from_user.id
    message_id = int(callback_query.data.split("_")[2])
    check = await is_autho_user_exist(user_id)
    if not check:
        await callback_query.answer("You are not authorized to perform this action.", show_alert=True)
        return

    # Get the original message
    message = callback_query.message
    chat_id = message.chat.id

    # Check if the message has a document
    if not message.reply_to_message or not message.reply_to_message.document:
        await callback_query.answer("No document found to convert.", show_alert=True)
        return

    document = message.reply_to_message.document
    if not document.file_name.endswith(".zip"):
        await callback_query.answer("Please send a ZIP file for conversion.", show_alert=True)
        return

    zip_name = os.path.splitext(document.file_name)[0]
    await callback_query.message.edit_text("📂 Processing your ZIP file...")

    # Use temporary directory
    with tempfile.TemporaryDirectory() as temp_dir:
        zip_path = os.path.join(temp_dir, document.file_name)
        extract_folder = os.path.join(temp_dir, f"{zip_name}_extracted")
        pdf_path = os.path.join(temp_dir, f"{zip_name}.pdf")

        # Download ZIP file
        try:
            await message.reply_to_message.download(zip_path)
        except Exception as e:
            await callback_query.message.edit_text(f"❌ Error downloading file: {e}")
            return

        # Extract ZIP file
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_folder)
        except zipfile.BadZipFile:
            await callback_query.message.edit_text("❌ Invalid ZIP file.")
            return

        # Supported image formats
        valid_extensions = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff", ".img")

        # Get image files, sorted naturally
        image_files = natural_sort([
            os.path.join(extract_folder, f) for f in os.listdir(extract_folder)
            if f.lower().endswith(valid_extensions)
        ])

        if not image_files:
            await callback_query.message.edit_text("❌ No images found in the ZIP.")
            return

        # Convert images to PDF without compression
        try:
            first_image = Image.open(image_files[0]).convert("RGB")
            image_list = [Image.open(img).convert("RGB") for img in image_files[1:]]
            first_image.save(pdf_path, save_all=True, append_images=image_list)
        except Exception as e:
            await callback_query.message.edit_text(f"❌ Error converting to PDF: {e}")
            return

        # Upload PDF
        try:
            await client.send_document(
                chat_id=chat_id,
                document=pdf_path,
                caption=f"Here is your PDF: {zip_name}.pdf 📄",
                reply_to_message_id=message_id
            )
            await callback_query.message.edit_text("✅ PDF generated and sent!")
        except Exception as e:
            await callback_query.message.edit_text(f"❌ Error uploading PDF: {e}")

@Client.on_callback_query(filters.regex("close"))
async def handle_close_callback(client: Client, callback_query):
    await callback_query.message.delete()
    await callback_query.answer("Message closed.")

@Client.on_message(filters.private & filters.command("pdf"))
async def pdf_handler(client: Client, message: Message):
    user_id = message.from_user.id
    check = await is_autho_user_exist(user_id) or user_id in ADMIN_IDS
    if not check:
        await message.reply_text(
            f"<b>⚠️ You are not authorized to use this command ⚠️</b>\n"
            f"<blockquote>Contact {SUPPORT_CHAT} to get authorized.</blockquote>",
            parse_mode="html"
        )
        return

    await message.reply_text("📂 Please send a ZIP file containing images. You have 30 seconds.")

    try:
        zip_msg = await client.listen(
            message.chat.id,
            filters=filters.document & filters.create(lambda _, __, m: m.document and m.document.file_name.endswith(".zip")),
            timeout=30
        )
    except asyncio.TimeoutError:
        return await message.reply_text("⏰ Timeout: No ZIP file received within 30 seconds.")

    zip_name = os.path.splitext(zip_msg.document.file_name)[0]

    # Use temporary directory
    with tempfile.TemporaryDirectory() as temp_dir:
        zip_path = os.path.join(temp_dir, zip_msg.document.file_name)
        extract_folder = os.path.join(temp_dir, f"{zip_name}_extracted")
        pdf_path = os.path.join(temp_dir, f"{zip_name}.pdf")

        # Download ZIP file
        try:
            await zip_msg.download(zip_path)
        except Exception as e:
            return await message.reply_text(f"❌ Error downloading file: {e}")

        # Extract ZIP file
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_folder)
        except zipfile.BadZipFile:
            return await message.reply_text("❌ Invalid ZIP file.")

        # Supported image formats
        valid_extensions = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff", ".img")

        # Get image files, sorted naturally
        image_files = natural_sort([
            os.path.join(extract_folder, f) for f in os.listdir(extract_folder)
            if f.lower().endswith(valid_extensions)
        ])

        if not image_files:
            return await message.reply_text("❌ No images found in the ZIP.")

        # Convert images to PDF without compression
        try:
            first_image = Image.open(image_files[0]).convert("RGB")
            image_list = [Image.open(img).convert("RGB") for img in image_files[1:]]
            first_image.save(pdf_path, save_all=True, append_images=image_list)
        except Exception as e:
            return await message.reply_text(f"❌ Error converting to PDF: {e}")

        # Upload PDF
        try:
            await message.reply_document(
                document=pdf_path,
                caption=f"Here is your PDF: {zip_name}.pdf 📄"
            )
        except Exception as e:
            return await message.reply_text(f"❌ Error uploading PDF: {e}")
