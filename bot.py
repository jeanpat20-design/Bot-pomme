import json
import logging
import os

from telegram import InlineKeyboardButton as B
from telegram import InlineKeyboardMarkup as M
from telegram import KeyboardButton, ReplyKeyboardMarkup, Update, WebAppInfo
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(level=logging.INFO)

# --- Variables d'environnement (à définir sur l'hébergeur) ---
TOKEN = os.environ["TOKEN"]  # token donné par @BotFather
BASE_URL = os.environ["BASE_URL"].rstrip("/")  # URL publique du bot
ADMIN_ID = os.environ.get("ADMIN_ID")  # ton ID Telegram (via @userinfobot)
WEBAPP_URL = os.environ.get("WEBAPP_URL")  # URL du site statique (Mini App)
PORT = int(os.environ.get("PORT", 8000))

# --- Catalogue : 5 pays (prix en € par kg). Garde-le identique à webapp/index.html ---
CATALOGUE = {
    "🇫🇷 France": {"Pink Lady": 3.5, "Reine des Reinettes": 3.2, "Gala": 2.8},
    "🇯🇵 Japon": {"Fuji": 6.0, "Sekai-ichi": 9.5},
    "🇳🇿 Nouvelle-Zélande": {"Jazz": 4.5, "Braeburn": 4.0},
    "🇺🇸 États-Unis": {"Honeycrisp": 5.0, "Red Delicious": 3.0},
    "🇮🇹 Italie": {"Golden Delicious": 3.0, "Annurca": 4.2},
}
PAYS = list(CATALOGUE)


async def show(update: Update, text: str, kb: M) -> None:
    q = update.callback_query
    if q:
        await q.edit_message_text(text, reply_markup=kb)
    else:
        await update.message.reply_text(text, reply_markup=kb)


async def menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    # Bouton permanent qui ouvre la Mini App (nécessaire pour qu'elle renvoie la commande)
    if WEBAPP_URL and update.message:
        clavier = ReplyKeyboardMarkup(
            [[KeyboardButton("🍎 Ouvrir la boutique", web_app=WebAppInfo(WEBAPP_URL))]],
            resize_keyboard=True,
        )
        await update.message.reply_text("Touche le bouton en bas pour ouvrir la boutique 👇", reply_markup=clavier)
    rows = [[B(p, callback_data=f"c:{i}")] for i, p in enumerate(PAYS)]
    rows.append([B("🛒 Mon panier", callback_data="cart")])
    await show(update, "🍎 Ou choisis un pays ici :", M(rows))


async def pays(update: Update, ctx: ContextTypes.DEFAULT_TYPE, ci: int) -> None:
    nom = PAYS[ci]
    rows = []
    for ai, (pomme, prix) in enumerate(CATALOGUE[nom].items()):
        rows.append([B(f"➕ {pomme} — {prix:.2f} €/kg", callback_data=f"a:{ci}:{ai}")])
    rows.append([B("🛒 Panier", callback_data="cart"), B("⬅️ Pays", callback_data="menu")])
    await show(update, f"{nom}\nAjoute des pommes (1 kg par appui) :", M(rows))


def lignes_panier(cart: dict):
    lignes, total = [], 0.0
    for key, qte in cart.items():
        ci, ai = map(int, key.split(":"))
        pomme, prix = list(CATALOGUE[PAYS[ci]].items())[ai]
        lignes.append(f"• {pomme} ({PAYS[ci]}) x{qte} kg = {prix * qte:.2f} €")
        total += prix * qte
    return lignes, total


async def panier(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cart = ctx.user_data.get("cart", {})
    if not cart:
        kb = M([[B("⬅️ Pays", callback_data="menu")]])
        await show(update, "Ton panier est vide.", kb)
        return
    lignes, total = lignes_panier(cart)
    texte = "🛒 Ton panier :\n" + "\n".join(lignes) + f"\n\nTotal : {total:.2f} €"
    kb = M(
        [
            [B("✅ Commander", callback_data="order")],
            [B("🗑 Vider", callback_data="clear"), B("⬅️ Pays", callback_data="menu")],
        ]
    )
    await show(update, texte, kb)


async def boutons(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    data = q.data
    if data == "menu":
        await q.answer()
        await menu(update, ctx)
    elif data.startswith("c:"):
        await q.answer()
        await pays(update, ctx, int(data.split(":")[1]))
    elif data.startswith("a:"):
        _, ci, ai = data.split(":")
        cart = ctx.user_data.setdefault("cart", {})
        key = f"{ci}:{ai}"
        cart[key] = cart.get(key, 0) + 1
        await q.answer("Ajouté au panier ✅")
    elif data == "cart":
        await q.answer()
        await panier(update, ctx)
    elif data == "clear":
        ctx.user_data["cart"] = {}
        await q.answer("Panier vidé")
        await panier(update, ctx)
    elif data == "order":
        if not ctx.user_data.get("cart"):
            await q.answer("Panier vide", show_alert=True)
            return
        await q.answer()
        ctx.user_data["await_addr"] = True
        await q.message.reply_text("📦 Envoie-moi ton nom et ton adresse de livraison :")


async def webapp_data(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Reçoit le panier envoyé par la Mini App."""
    msg = update.effective_message
    try:
        items = json.loads(msg.web_app_data.data)
    except ValueError:
        return
    cart = {}
    for key, qte in items.items():
        nom_pays, _, pomme = key.partition("|")
        if nom_pays in CATALOGUE and pomme in CATALOGUE[nom_pays]:
            if isinstance(qte, int) and 0 < qte <= 50:
                ci = PAYS.index(nom_pays)
                ai = list(CATALOGUE[nom_pays]).index(pomme)
                cart[f"{ci}:{ai}"] = qte  # les prix viennent du bot, pas de la Mini App
    if not cart:
        await msg.reply_text("Ton panier est vide.")
        return
    ctx.user_data["cart"] = cart
    ctx.user_data["await_addr"] = True
    lignes, total = lignes_panier(cart)
    await msg.reply_text(
        "🛒 Ta commande :\n" + "\n".join(lignes) + f"\n\nTotal : {total:.2f} €"
        "\n\n📦 Envoie-moi ton nom et ton adresse de livraison :"
    )


async def texte(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.user_data.get("await_addr"):
        await update.message.reply_text("Tape /start pour voir la boutique 🍎")
        return
    lignes, total = lignes_panier(ctx.user_data.get("cart", {}))
    user = update.effective_user
    commande = (
        f"🆕 Commande de @{user.username or user.first_name}\n"
        + "\n".join(lignes)
        + f"\nTotal : {total:.2f} €\n\nLivraison :\n{update.message.text}"
    )
    if ADMIN_ID:
        await ctx.bot.send_message(chat_id=ADMIN_ID, text=commande)
    else:
        logging.info(commande)
    ctx.user_data["cart"] = {}
    ctx.user_data["await_addr"] = False
    await update.message.reply_text("Merci ! Ta commande est enregistrée 🍏 Je te recontacte vite.")


def main() -> None:
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", menu))
    app.add_handler(CommandHandler("panier", panier))
    app.add_handler(CallbackQueryHandler(boutons))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, webapp_data))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, texte))
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"{BASE_URL}/{TOKEN}",
    )


if __name__ == "__main__":
    main()
