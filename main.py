import os
import time
import random
import string
import threading
import requests
import telebot
from telebot import types
from dotenv import load_dotenv

# ================== KONFIGURASI ==================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))  # ID Telegram admin (cek pakai /myid)
API_BASE = "https://api.mail.tm"

if not BOT_TOKEN or not ADMIN_ID:
    raise RuntimeError("Harap set BOT_TOKEN dan ADMIN_ID di file .env")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")

# ================== PENYIMPANAN SEMENTARA ==================
# Per user_id -> { email, token, seen_ids:set() }
sessions = {}
# Daftar semua user yang pernah start (untuk broadcast)
all_users = set()

# ================== UTIL & API ==================
def rnd(n=8):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

def mailtm_get_domains():
    r = requests.get(f"{API_BASE}/domains", timeout=15)
    r.raise_for_status()
    items = r.json().get("hydra:member", [])
    if not items:
        raise RuntimeError("Tidak ada domain tersedia dari Mail.tm")
    return [it["domain"] for it in items]

def mailtm_create_account():
    """Buat akun Mail.tm valid: ambil domain resmi, registrasi, lalu login -> token."""
    try:
        domain = random.choice(mailtm_get_domains())
        address = f"{rnd()}@{domain}"
        password = rnd(12)

        # Daftarkan akun
        requests.post(f"{API_BASE}/accounts", json={"address": address, "password": password}, timeout=20)

        # Login untuk ambil token
        resp = requests.post(f"{API_BASE}/token", json={"address": address, "password": password}, timeout=20)
        if resp.status_code != 200:
            return None, None

        token = resp.json().get("token")
        return address, token
    except Exception as e:
        print("create_account error:", e)
        return None, None

def mailtm_list_messages(token):
    try:
        headers = {"Authorization": f"Bearer {token}"}
        r = requests.get(f"{API_BASE}/messages", headers=headers, timeout=20)
        if r.status_code != 200:
            return []
        return r.json().get("hydra:member", [])
    except Exception as e:
        print("list_messages error:", e)
        return []

def mailtm_get_message(token, msg_id):
    try:
        headers = {"Authorization": f"Bearer {token}"}
        r = requests.get(f"{API_BASE}/messages/{msg_id}", headers=headers, timeout=20)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception as e:
        print("get_message error:", e)
        return None

# ================== UI HELPERS ==================
def main_menu(is_admin=False):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    row1 = [types.KeyboardButton("📧 Buat Email"), types.KeyboardButton("📥 Cek Inbox")]
    row2 = [types.KeyboardButton("ℹ️ About"), types.KeyboardButton("☕ Donate")]
    kb.add(*row1)
    kb.add(*row2)
    if is_admin:
        kb.add(types.KeyboardButton("🛠 Admin Menu"))
    return kb

WELCOME_TEXT = (
    "👋 *Selamat datang di TempMailBot!*\n\n"
    "Bot ini membantu kamu membuat *email sementara* untuk mendaftar layanan, menerima OTP, "
    "atau melindungi privasi dari spam.\n\n"
    "✨ *Fitur Utama:*\n"
    "• 📧 Buat email sementara (`/getmail`)\n"
    "• 📥 Cek inbox & baca email (`/inbox`, `/read <ID>`)\n"
    "• 🔔 Auto-notifikasi: email baru akan dikirim otomatis ke chat kamu\n"
    "• ℹ️ Info bot & dukungan (`/about`, `/donate`)\n"
    "• 👨‍💻 Admin panel & broadcast (khusus owner)\n\n"
    "⚡ *Cara cepat:* Tekan tombol menu di bawah atau ketik perintah.\n"
)

ABOUT_TEXT = (
    "🤖 *Tentang Bot TempMail*\n\n"
    "Bot ini menyediakan email sementara (temporary/disposable). "
    "Cocok untuk testing, verifikasi akun, dan menghindari spam.\n\n"
    "📌 *Menu Ringkas:*\n"
    "• `/getmail` / `/getemail` → Buat email baru\n"
    "• `/inbox` → Lihat inbox saat ini\n"
    "• `/read <ID>` → Baca isi email tertentu\n"
    "• `/myid` → Lihat ID Telegram kamu\n"
    "• `/donate` → Dukung pengembang\n"
)

DONATE_TEXT = (
    "☕ *Dukung Pengembang*\n\n"
    "👨‍💻 Pembuat: *@Hiicylne*\n"
    "Deskripsi: Bot email sementara dengan auto-refresh inbox.\n\n"
    "Kalau bot ini bermanfaat, kamu bisa dukung di sini:\n"
    "🔗 Saweria: https://saweria.co/CYLNE\n"
    "🔗 Dana: +62 895-0761-3594\n\n"
    "Terima kasih! 🙏"
)

# ================== COMMAND HANDLERS ==================
@bot.message_handler(commands=["start"])
def cmd_start(message):
    all_users.add(message.from_user.id)
    is_admin = (message.from_user.id == ADMIN_ID)
    bot.reply_to(message, WELCOME_TEXT, reply_markup=main_menu(is_admin=is_admin))

@bot.message_handler(commands=["help"])
def cmd_help(message):
    bot.reply_to(message, ABOUT_TEXT)

@bot.message_handler(commands=["myid"])
def cmd_myid(message):
    bot.reply_to(message, f"🆔 *Telegram ID:* `{message.from_user.id}`")

@bot.message_handler(commands=["about"])
def cmd_about(message):
    bot.reply_to(message, ABOUT_TEXT)

@bot.message_handler(commands=["donate"])
def cmd_donate(message):
    bot.reply_to(message, DONATE_TEXT)

# Kedua alias: /getmail dan /getemail
@bot.message_handler(commands=["getmail", "getemail"])
def cmd_getmail(message):
    all_users.add(message.from_user.id)
    email, token = mailtm_create_account()
    if not email:
        bot.reply_to(message, "❌ Gagal membuat email. Coba lagi beberapa saat.")
        return

    sessions[message.from_user.id] = {
        "email": email,
        "token": token,
        "seen_ids": set()
    }
    bot.reply_to(
        message,
        f"✅ *Email sementara dibuat!*\n\n"
        f"📧 `{email}`\n\n"
        f"Gunakan untuk menerima pesan. Ketik `/inbox` untuk cek, "
        f"atau tunggu — bot akan kirim notifikasi otomatis jika ada email baru."
    )

@bot.message_handler(commands=["inbox"])
def cmd_inbox(message):
    sess = sessions.get(message.from_user.id)
    if not sess:
        bot.reply_to(message, "⚠️ Kamu belum punya email. Buat dulu pakai `/getmail`.")
        return

    msgs = mailtm_list_messages(sess["token"])
    if not msgs:
        bot.reply_to(message, "📭 *Inbox kosong.*")
        return

    lines = ["📥 *Inbox Saat Ini:*\n"]
    for m in msgs:
        from_addr = m.get("from", {}).get("address", "-")
        subject = m.get("subject", "(tanpa subjek)")
        mid = m.get("id")
        created = m.get("createdAt", "").replace("T", " ").replace("Z", " UTC")
        lines.append(f"— 🆔 `{mid}`\n  📝 *Dari:* {from_addr}\n  📌 *Subjek:* {subject}\n  🕒 {created}\n")
    lines.append("Gunakan `/read <ID>` untuk membaca isi email.")
    bot.reply_to(message, "\n".join(lines))

@bot.message_handler(commands=["read"])
def cmd_read(message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.reply_to(message, "Format: `/read <ID>`")
        return

    sess = sessions.get(message.from_user.id)
    if not sess:
        bot.reply_to(message, "⚠️ Kamu belum punya email. Buat dulu pakai `/getmail`.")
        return

    msg_id = args[1].strip()
    msg = mailtm_get_message(sess["token"], msg_id)
    if not msg:
        bot.reply_to(message, "❌ Gagal membaca pesan. ID salah atau email sudah kadaluarsa.")
        return

    from_addr = msg.get("from", {}).get("address", "-")
    subject = msg.get("subject", "(tanpa subjek)")
    text_body = msg.get("text", "(tidak ada isi teks)")
    created = msg.get("createdAt", "").replace("T", " ").replace("Z", " UTC")

    reply = (
        f"📨 *Email:*\n"
        f"📝 *Dari:* {from_addr}\n"
        f"📌 *Subjek:* {subject}\n"
        f"🕒 {created}\n\n"
        f"{text_body}"
    )
    bot.reply_to(message, reply)

# ================== ADMIN ==================
@bot.message_handler(commands=["admin"])
def cmd_admin(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "🚫 Akses ditolak. Menu ini khusus admin.")
        return

    total_users = len(all_users)
    active_emails = [s["email"] for s in sessions.values()]
    text = (
        "🛠 *Admin Panel*\n\n"
        f"👥 Total user terdaftar: *{total_users}*\n"
        f"📧 Email aktif: {len(active_emails)}\n"
        f"🗒 Daftar email: {', '.join(active_emails) if active_emails else '-'}"
    )

    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("⬅️ Back"))
    bot.reply_to(message, text, reply_markup=kb)

@bot.message_handler(commands=["broadcast"])
def cmd_broadcast(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "🚫 Akses ditolak. Menu ini khusus admin.")
        return

    parts = message.text.split(" ", 1)
    if len(parts) < 2 or not parts[1].strip():
        bot.reply_to(message, "Format: `/broadcast Pesan anda di sini`")
        return

    text = parts[1].strip()
    sent = 0
    for uid in list(all_users):
        try:
            bot.send_message(uid, f"📢 *Broadcast:*\n\n{text}")
            sent += 1
        except Exception:
            pass
    bot.reply_to(message, f"✅ Broadcast terkirim ke *{sent}* user.")

# ================== HANDLER TOMBOL TEKS ==================
@bot.message_handler(func=lambda m: m.text in ["📧 Buat Email", "📥 Cek Inbox", "ℹ️ About", "☕ Donate", "🛠 Admin Menu", "⬅️ Back"])
def handle_buttons(message):
    if message.text == "📧 Buat Email":
        cmd_getmail(message)
    elif message.text == "📥 Cek Inbox":
        cmd_inbox(message)
    elif message.text == "ℹ️ About":
        cmd_about(message)
    elif message.text == "☕ Donate":
        cmd_donate(message)
    elif message.text == "🛠 Admin Menu":
        cmd_admin(message)
    elif message.text == "⬅️ Back":
        is_admin = (message.from_user.id == ADMIN_ID)
        bot.reply_to(message, "Kembali ke menu utama.", reply_markup=main_menu(is_admin))

# ================== AUTO-REFRESH INBOX ==================
def watcher_loop():
    while True:
        time.sleep(30)  # interval cek
        for uid, sess in list(sessions.items()):
            token = sess.get("token")
            if not token:
                continue

            msgs = mailtm_list_messages(token)
            if not msgs:
                continue

            seen = sess.get("seen_ids", set())
            new_msgs = [m for m in msgs if m.get("id") not in seen]

            for m in new_msgs:
                mid = m.get("id")
                from_addr = m.get("from", {}).get("address", "-")
                subject = m.get("subject", "(tanpa subjek)")
                created = m.get("createdAt", "").replace("T", " ").replace("Z", " UTC")
                preview = m.get("intro", "")

                text = (
                    "📨 *Email Baru Masuk!*\n\n"
                    f"📝 *Dari:* {from_addr}\n"
                    f"📌 *Subjek:* {subject}\n"
                    f"🕒 {created}\n"
                    f"🧾 *Preview:* {preview}\n\n"
                    f"Gunakan `/read {mid}` untuk membaca isi lengkap."
                )
                try:
                    bot.send_message(uid, text)
                except Exception:
                    pass
                seen.add(mid)

            sess["seen_ids"] = seen
            sessions[uid] = sess

# Jalankan watcher di thread daemon
threading.Thread(target=watcher_loop, daemon=True).start()

# ================== RUN ==================
print("🤖 TempMailBot berjalan dengan auto-refresh...")
bot.infinity_polling(skip_pending=True)