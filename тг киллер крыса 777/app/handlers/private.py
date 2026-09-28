from html import escape

from aiogram import F, Router
from aiogram.enums import ChatType, MessageEntityType
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app import game, texts
from app.config import ADMIN_IDS
from app.emoji import em
from app.ui import btn, kb, safe_edit

PHRASE_LIMIT = 200

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)


class RewardInput(StatesGroup):
    phrase = State()


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    markup = None
    if message.from_user.id in ADMIN_IDS:
        markup = kb([btn("Открыть админ-панель", "a:home", emoji="settings", style="primary")])
    await message.reply(
        texts.rules_text(
            "Бот ивента 777",
            f"{em('info')} Добавь меня в группу админом и запусти ивент: /game 20h",
        ),
        reply_markup=markup,
    )


@router.message(Command("rules"))
async def cmd_rules(message: Message):
    await message.reply(texts.rules_text())


@router.message(Command("id"))
async def cmd_id(message: Message):
    await message.reply(f"Твой ID: <code>{message.from_user.id}</code>")


# ─── Награда чемпиона: свои фразы для киллера и крысы ─────────────────────

def reward_view(user_id: int):
    legend = game.get_legend(user_id)
    killer = escape(legend["killer_phrase"]) or "<i>не задана</i>"
    rat = escape(legend["rat_phrase"]) or "<i>не задана</i>"
    text = (
        f"{em('crown')} <b>Награда чемпиона</b> · побед: {legend['wins']}\n\n"
        f"Придумай фразу, которую будут иногда говорить персонажи ивента — "
        f"с подписью, что это фраза чемпиона.\n\n"
        f"{em('killer')} Киллер: {killer}\n"
        f"{em('rat')} Крыса: {rat}"
    )
    markup = kb(
        [btn("Фраза киллера", "rw:killer", emoji="killer", style="primary")],
        [btn("Фраза крысы", "rw:rat", emoji="rat", style="primary")],
    )
    return text, markup


@router.message(Command("reward"))
async def cmd_reward(message: Message, state: FSMContext):
    await state.clear()
    if not game.is_legend(message.from_user.id):
        await message.reply(f"{em('winner')} Награда откроется, когда ты выиграешь ивент 777.")
        return
    await message.reply(*reward_view(message.from_user.id))


@router.callback_query(F.data.startswith("rw:"))
async def on_reward_pick(call: CallbackQuery, state: FSMContext):
    if not game.is_legend(call.from_user.id):
        await call.answer("Только для чемпионов.", show_alert=True)
        return
    kind = call.data.split(":")[1]
    who = "киллера" if kind == "killer" else "крысы"
    await state.set_state(RewardInput.phrase)
    await state.update_data(kind=kind)
    await call.answer()
    await safe_edit(
        call.message,
        f"{em('edit')} Напиши фразу для {who} одним сообщением (до {PHRASE_LIMIT} символов).",
        kb([btn("Отмена", "rw_cancel", emoji="back", style="danger")]),
    )


@router.callback_query(F.data == "rw_cancel")
async def on_reward_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    if game.is_legend(call.from_user.id):
        await safe_edit(call.message, *reward_view(call.from_user.id))


@router.message(RewardInput.phrase)
async def on_reward_phrase(message: Message, state: FSMContext):
    phrase = (message.text or "").strip()
    if not phrase or len(phrase) > PHRASE_LIMIT:
        await message.reply(f"{em('warn')} Нужен текст до {PHRASE_LIMIT} символов.")
        return
    data = await state.get_data()
    await state.clear()
    game.set_legend_phrase(message.from_user.id, data["kind"], phrase)
    await message.reply(f"{em('safe')} Сохранено!")
    await message.reply(*reward_view(message.from_user.id))


# ─── Помощник для админа: ID премиум-эмодзи ───────────────────────────────

@router.message(StateFilter(None), F.from_user.id.in_(ADMIN_IDS))
async def emoji_ids(message: Message):
    found = []
    if message.sticker and message.sticker.custom_emoji_id:
        found.append((message.sticker.emoji or "?", message.sticker.custom_emoji_id))
    for entity in message.entities or []:
        if entity.type == MessageEntityType.CUSTOM_EMOJI:
            found.append((entity.extract_from(message.text), entity.custom_emoji_id))
    if not found:
        await message.reply(
            f"{em('info')} Команды: /admin — панель, /id — твой ID.\n"
            f"Пришли премиум-эмодзи — покажу его ID для файла <code>app/emoji.py</code>."
        )
        return
    lines = [f'<tg-emoji emoji-id="{eid}">{escape(char)}</tg-emoji> <code>{eid}</code>' for char, eid in found]
    await message.reply("<b>ID премиум-эмодзи:</b>\n" + "\n".join(lines))
