from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
import json
from pathlib import Path
from datetime import date
import httpx


TOKEN = "8225336814:AAF-iTsLTp55WlSioTxwScB3hTS63l5zSYU"
OPENWEATHER_API_KEY = "133891c5d4ce5651e1e373e5e980daf8" 
DATA_FILE = Path(__file__).parent / "data.json"


# =========================
# DATA
# =========================
def load_data():
    if DATA_FILE.exists():
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
    else:
        data = {}

    data.setdefault("car", {})
    for k in ["gtp", "vinetka", "maslo", "obslujvane"]:
        data["car"].setdefault(k, "")

    data.setdefault("birthdays", [])
    if not isinstance(data["birthdays"], list):
        data["birthdays"] = []

    data.setdefault("tasks", [])
    if not isinstance(data["tasks"], list):
        data["tasks"] = []

    data.setdefault("tasks_done", [])
    if not isinstance(data["tasks_done"], list):
        data["tasks_done"] = []

    data.setdefault("orders", {})
    data["orders"].setdefault("suppliers", [])
    if not isinstance(data["orders"]["suppliers"], list):
        data["orders"]["suppliers"] = []

    # settings
    data.setdefault("settings", {})
    data["settings"].setdefault("city", "Sofia,BG")  # можеш да го смениш от Настройки

    return data


def save_data(data):
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# =========================
# DATE HELPERS
# =========================
def parse_bg_date_full(s: str):
    """ДД.ММ.ГГГГ -> date or None"""
    s = (s or "").strip()
    parts = s.split(".")
    if len(parts) != 3:
        return None
    try:
        d = int(parts[0]); m = int(parts[1]); y = int(parts[2])
        return date(y, m, d)
    except Exception:
        return None


def days_left_text(date_str: str):
    dt = parse_bg_date_full(date_str)
    if not dt:
        return None
    today = date.today()
    diff = (dt - today).days
    if diff > 0:
        return f"⏳ Остават {diff} дни"
    if diff == 0:
        return "📌 Изтича днес"
    return f"⚠️ Изтекло преди {-diff} дни"


def parse_bday(date_str: str):
    """ДД.ММ или ДД.ММ.ГГГГ -> (day, month) or None"""
    try:
        parts = (date_str or "").strip().split(".")
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
        if len(parts) == 3:
            return int(parts[0]), int(parts[1])
    except Exception:
        return None
    return None


def days_until_birthday(day: int, month: int):
    today = date.today()
    y = today.year
    nxt = date(y, month, day)
    if nxt < today:
        nxt = date(y + 1, month, day)
    return (nxt - today).days, nxt


def bday_is_today(date_str: str) -> bool:
    p = parse_bday(date_str)
    if not p:
        return False
    d, m = p
    t = date.today()
    return (t.day == d) and (t.month == m)


# =========================
# ORDERS helpers (days buttons)
# =========================
WEEKDAY_BG = {
    0: "Понеделник",
    1: "Вторник",
    2: "Сряда",
    3: "Четвъртък",
    4: "Петък",
    5: "Събота",
    6: "Неделя",
}

DAYS = [
    ("Пон", "Понеделник"),
    ("Вт", "Вторник"),
    ("Ср", "Сряда"),
    ("Чет", "Четвъртък"),
    ("Пет", "Петък"),
    ("Съб", "Събота"),
    ("Нед", "Неделя"),
]


def selected_days_text(selected_full_days):
    if not selected_full_days:
        return "—"
    ordered = [full for _, full in DAYS if full in selected_full_days]
    return ", ".join(ordered)


def orders_days_keyboard(selected_full_days):
    rows = []
    row1 = []
    for i in range(4):
        short, full = DAYS[i]
        mark = "✅" if full in selected_full_days else "⬜"
        row1.append(InlineKeyboardButton(f"{mark} {short}", callback_data=f"orders:day:{i}"))
    rows.append(row1)

    row2 = []
    for i in range(4, 7):
        short, full = DAYS[i]
        mark = "✅" if full in selected_full_days else "⬜"
        row2.append(InlineKeyboardButton(f"{mark} {short}", callback_data=f"orders:day:{i}"))
    rows.append(row2)

    rows.append([
        InlineKeyboardButton("🧼 Изчисти", callback_data="orders:days_clear"),
        InlineKeyboardButton("✅ Готово", callback_data="orders:days_done"),
    ])
    rows.append([InlineKeyboardButton("❌ Отказ", callback_data="orders:days_cancel")])
    return InlineKeyboardMarkup(rows)


def orders_pick_supplier_keyboard(suppliers):
    rows = []
    for i, s in enumerate(suppliers, 1):
        name = s.get("name", "—")
        rows.append([InlineKeyboardButton(f"{i}. {name}", callback_data=f"orders:edit_pick:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="menu:orders")])
    return InlineKeyboardMarkup(rows)


# =========================
# TASKS helpers
# =========================
def tasks_pick_keyboard(tasks):
    rows = []
    for i, t in enumerate(tasks[:30], 1):
        title = t.get("text", "—")
        d = t.get("date", "")
        label = f"{i}. {title}" + (f" ({d})" if d else "")
        rows.append([InlineKeyboardButton(label[:60], callback_data=f"tasks:done:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="menu:tasks")])
    return InlineKeyboardMarkup(rows)


def tasks_show_keyboard(tasks, offset):
    rows = []
    for i, t in enumerate(tasks, 1):
        abs_index = offset + (i - 1)
        d = t.get("date", "")
        label = f"✔️ {i}" + (f" ({d})" if d else "")
        rows.append([InlineKeyboardButton(label[:64], callback_data=f"tasks:done_abs:{abs_index}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="menu:tasks")])
    return InlineKeyboardMarkup(rows)


# =========================
# BIRTHDAYS helpers (edit/delete with buttons)
# =========================
def bdays_list_keyboard(items, offset):
    rows = []
    for i, it in enumerate(items, 1):
        abs_index = offset + (i - 1)
        name = it.get("name", "—")
        d = it.get("date", "—")
        rows.append([
            InlineKeyboardButton(f"✏️ {i}", callback_data=f"bdays:edit_abs:{abs_index}"),
            InlineKeyboardButton(f"🗑️ {i}", callback_data=f"bdays:del_abs:{abs_index}"),
            InlineKeyboardButton(f"{name} ({d})"[:35], callback_data=f"bdays:view_abs:{abs_index}"),
        ])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="menu:bdays")])
    return InlineKeyboardMarkup(rows)


def bdays_confirm_delete_kb(abs_index):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Да, изтрий", callback_data=f"bdays:del_yes:{abs_index}"),
         InlineKeyboardButton("❌ Не", callback_data="bdays:del_no")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="menu:bdays")]
    ])


# =========================
# UI (menus)
# =========================
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("☀️ Времето днес", callback_data="weather:today")],
        [InlineKeyboardButton("📅 Какво има днес", callback_data="today:show")],
        [InlineKeyboardButton("🚗 Кола", callback_data="menu:car")],
        [InlineKeyboardButton("🎂 Рождени дни", callback_data="menu:bdays")],
        [InlineKeyboardButton("✅ Лични задачи", callback_data="menu:tasks")],
        [InlineKeyboardButton("📦 Поръчки", callback_data="menu:orders")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="menu:settings")],
    ])


def settings_menu(data):
    city = data.get("settings", {}).get("city", "Sofia,BG")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🏙️ Град: {city}", callback_data="settings:city_show")],
        [InlineKeyboardButton("✏️ Смени град", callback_data="settings:city_set")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back:main")],
    ])


def car_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛠️ ГТП", callback_data="car:show:gtp"),
         InlineKeyboardButton("✏️ Промени", callback_data="car:set:gtp")],

        [InlineKeyboardButton("🛣️ Винетка", callback_data="car:show:vinetka"),
         InlineKeyboardButton("✏️ Промени", callback_data="car:set:vinetka")],

        [InlineKeyboardButton("🛢️ Масло", callback_data="car:show:maslo"),
         InlineKeyboardButton("✏️ Промени", callback_data="car:set:maslo")],

        [InlineKeyboardButton("🔧 Обслужване", callback_data="car:show:obslujvane"),
         InlineKeyboardButton("✏️ Промени", callback_data="car:set:obslujvane")],

        [InlineKeyboardButton("👀 Покажи всички", callback_data="car:show_all")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back:main")],
    ])


def bdays_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добави рожден ден", callback_data="bdays:add")],
        [InlineKeyboardButton("👀 Покажи всички (с бутони)", callback_data="bdays:show_buttons")],
        [InlineKeyboardButton("⭐ Следващ рожден ден", callback_data="bdays:next")],
        [InlineKeyboardButton("🧹 Изчисти всички", callback_data="bdays:clear")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back:main")],
    ])


def tasks_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добави задача", callback_data="tasks:add")],
        [InlineKeyboardButton("👀 Покажи всички", callback_data="tasks:show")],
        [InlineKeyboardButton("📅 Предстоящи", callback_data="tasks:upcoming")],
        [InlineKeyboardButton("✔️ Отметни изпълнена", callback_data="tasks:done_pick")],
        [InlineKeyboardButton("📜 История", callback_data="tasks:history")],
        [InlineKeyboardButton("🧹 Изчисти всички", callback_data="tasks:clear"),
         InlineKeyboardButton("🧹 Изчисти история", callback_data="tasks:history_clear")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back:main")],
    ])


def orders_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добави доставчик", callback_data="orders:add")],
        [InlineKeyboardButton("👀 Покажи доставчици", callback_data="orders:list")],
        [InlineKeyboardButton("✏️ Редакция на доставчик", callback_data="orders:edit")],
        [InlineKeyboardButton("🔎 Провери доставчик", callback_data="orders:check")],
        [InlineKeyboardButton("🧹 Изчисти всички", callback_data="orders:clear")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back:main")],
    ])


CAR_LABELS = {
    "gtp": "🛠️ ГТП",
    "vinetka": "🛣️ Винетка",
    "maslo": "🛢️ Смяна на масло",
    "obslujvane": "🔧 Обслужване",
}


def car_summary(data):
    c = data["car"]
    gtp_left = days_left_text(c.get("gtp", ""))
    vin_left = days_left_text(c.get("vinetka", ""))

    gtp_line = f"🛠️ ГТП: {c.get('gtp') or '—'}"
    if gtp_left:
        gtp_line += f"  •  {gtp_left}"

    vin_line = f"🛣️ Винетка: {c.get('vinetka') or '—'}"
    if vin_left:
        vin_line += f"  •  {vin_left}"

    return (
        "🚗 Данни за колата:\n"
        f"{gtp_line}\n"
        f"{vin_line}\n"
        f"🛢️ Масло: {c.get('maslo') or '—'}\n"
        f"🔧 Обслужване: {c.get('obslujvane') or '—'}"
    )


# =========================
# WEATHER
# =========================
async def get_weather_today(city: str) -> str:
    if not OPENWEATHER_API_KEY or OPENWEATHER_API_KEY == "ТУК_СЛОЖИ_OPENWEATHER_API_KEY":
        return "❌ Нямаш зададен OPENWEATHER_API_KEY в кода."

    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "q": city,
        "appid": OPENWEATHER_API_KEY,
        "units": "metric",
        "lang": "bg",
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, params=params)
        if r.status_code != 200:
            return f"❌ Не успях да взема времето за „{city}“. (код {r.status_code})"

        j = r.json()
        name = j.get("name", city)
        weather = (j.get("weather") or [{}])[0]
        desc = weather.get("description", "—")
        main = j.get("main") or {}
        wind = j.get("wind") or {}

        temp = main.get("temp")
        feels = main.get("feels_like")
        tmin = main.get("temp_min")
        tmax = main.get("temp_max")
        hum = main.get("humidity")
        ws = wind.get("speed")

        lines = [
            f"☀️ Времето днес – {name}",
            "────────────",
            f"☁️ {desc}",
        ]
        if temp is not None:
            lines.append(f"🌡️ Температура: {temp:.0f}°C")
        if feels is not None:
            lines.append(f"🤒 Усеща се: {feels:.0f}°C")
        if tmin is not None and tmax is not None:
            lines.append(f"📉 Мин: {tmin:.0f}°C  |  📈 Макс: {tmax:.0f}°C")
        if hum is not None:
            lines.append(f"💧 Влажност: {hum}%")
        if ws is not None:
            lines.append(f"💨 Вятър: {ws:.1f} m/s")

        return "\n".join(lines)

    except Exception:
        return "❌ Грешка при връзката за времето. Опитай пак след малко."


# =========================
# COMMANDS
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.chat_data.clear()
    await update.message.reply_text("📒 Меню", reply_markup=main_menu())


# =========================
# BUTTONS
# =========================
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = load_data()

    # WEATHER
    if q.data == "weather:today":
        city = data["settings"].get("city", "Sofia,BG")
        text = await get_weather_today(city)
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⚙️ Настройки", callback_data="menu:settings")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="back:main")]
        ]))
        return

    # SETTINGS
    if q.data == "menu:settings":
        context.chat_data.clear()
        await q.edit_message_text("⚙️ Настройки", reply_markup=settings_menu(data))
        return

    if q.data == "settings:city_show":
        city = data["settings"].get("city", "Sofia,BG")
        await q.edit_message_text(
            f"🏙️ Текущ град: {city}\n\nМожеш да го смениш от „✏️ Смени град“.",
            reply_markup=settings_menu(data)
        )
        return

    if q.data == "settings:city_set":
        context.chat_data.clear()
        context.chat_data["mode"] = "set_city"
        await q.edit_message_text(
            "✏️ Смяна на град\n\nНапиши град така:\n"
            "• Sofia,BG\n"
            "• Plovdiv,BG\n"
            "• Varna,BG\n\n"
            "Може и само: Sofia",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="menu:settings")]])
        )
        return

    # ---- Today ----
    if q.data == "today:show":
        today = date.today()
        weekday_name = WEEKDAY_BG[today.weekday()]

        suppliers_today = [
            s.get("name", "—")
            for s in data["orders"]["suppliers"]
            if weekday_name in (s.get("days", []) or [])
        ]

        tasks_today = []
        for t in data["tasks"]:
            dt = parse_bg_date_full(t.get("date", "")) if t.get("date") else None
            if dt and dt == today:
                tasks_today.append(t.get("text", "—"))

        bdays_today = [
            b.get("name", "—")
            for b in data["birthdays"]
            if bday_is_today(b.get("date", ""))
        ]

        lines = [
            f"📅 Днес: {today.strftime('%d.%m.%Y')} ({weekday_name})",
            "",
            "📦 Доставчици за днес:",
            *( [f"• {x}" for x in suppliers_today] if suppliers_today else ["— няма —"] ),
            "",
            "✅ Задачи за днес:",
            *( [f"• {x}" for x in tasks_today] if tasks_today else ["— няма —"] ),
            "",
            "🎂 Рождени дни днес:",
            *( [f"• {x}" for x in bdays_today] if bdays_today else ["— няма —"] ),
        ]
        await q.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data="back:main")]
        ]))
        return

    # back
    if q.data == "back:main":
        context.chat_data.clear()
        await q.edit_message_text("📒 Меню", reply_markup=main_menu())
        return

    # open menus
    if q.data == "menu:car":
        await q.edit_message_text("🚗 Кола", reply_markup=car_menu())
        return

    if q.data == "menu:bdays":
        context.chat_data.clear()
        await q.edit_message_text("🎂 Рождени дни", reply_markup=bdays_menu())
        return

    if q.data == "menu:tasks":
        await q.edit_message_text("✅ Лични задачи", reply_markup=tasks_menu())
        return

    if q.data == "menu:orders":
        await q.edit_message_text("📦 Поръчки", reply_markup=orders_menu())
        return

    # -------- CAR --------
    if q.data == "car:show_all":
        await q.edit_message_text(car_summary(data), reply_markup=car_menu())
        return

    if q.data.startswith("car:show:"):
        field = q.data.split(":")[2]
        value = data["car"].get(field) or "няма запис"
        extra = days_left_text(data["car"].get(field, "")) if field in ("gtp", "vinetka") else None

        text = f"{CAR_LABELS[field]}\n📅 Текущо: {value}"
        if extra:
            text += f"\n{extra}"

        await q.edit_message_text(text, reply_markup=car_menu())
        return

    if q.data.startswith("car:set:"):
        field = q.data.split(":")[2]
        context.chat_data["mode"] = "car_edit"
        context.chat_data["car_field"] = field

        current = data["car"].get(field) or "—"
        hint = "\n(за ГТП/Винетка: формат ДД.ММ.ГГГГ, пример 24.01.2026)" if field in ("gtp", "vinetka") else ""
        await q.edit_message_text(
            f"{CAR_LABELS[field]}\nТекущо: {current}\n\n✍️ Напиши нова стойност/дата:{hint}"
        )
        return

    # -------- BIRTHDAYS --------
    if q.data == "bdays:add":
        context.chat_data.clear()
        context.chat_data["mode"] = "bday_name"
        await q.edit_message_text("➕ Добавяне на рожден ден\n\nНапиши ИМЕ (пример: Мама):")
        return

    if q.data == "bdays:show_buttons":
        if not data["birthdays"]:
            await q.edit_message_text("🎂 Няма добавени рождени дни.", reply_markup=bdays_menu())
            return

        view = data["birthdays"][-30:]
        offset = len(data["birthdays"]) - len(view)

        lines = ["🎂 Рождени дни (последните 30):"]
        for i, it in enumerate(view, 1):
            lines.append(f"{i}. {it.get('name','—')} — {it.get('date','—')}")
        lines.append("\nНатисни ✏️ за редакция или 🗑️ за изтриване.")
        await q.edit_message_text("\n".join(lines), reply_markup=bdays_list_keyboard(view, offset))
        return

    if q.data.startswith("bdays:view_abs:"):
        abs_index = int(q.data.split(":")[2])
        if abs_index < 0 or abs_index >= len(data["birthdays"]):
            await q.edit_message_text("❌ Невалиден избор.", reply_markup=bdays_menu())
            return
        it = data["birthdays"][abs_index]
        await q.edit_message_text(
            f"🎂 {it.get('name','—')}\n📅 Дата: {it.get('date','—')}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✏️ Редакция", callback_data=f"bdays:edit_abs:{abs_index}"),
                 InlineKeyboardButton("🗑️ Изтрий", callback_data=f"bdays:del_abs:{abs_index}")],
                [InlineKeyboardButton("⬅️ Назад", callback_data="bdays:show_buttons")]
            ])
        )
        return

    if q.data.startswith("bdays:del_abs:"):
        abs_index = int(q.data.split(":")[2])
        if abs_index < 0 or abs_index >= len(data["birthdays"]):
            await q.edit_message_text("❌ Невалиден избор.", reply_markup=bdays_menu())
            return
        it = data["birthdays"][abs_index]
        await q.edit_message_text(
            f"🗑️ Да изтрия ли?\n\n🎂 {it.get('name','—')}\n📅 {it.get('date','—')}",
            reply_markup=bdays_confirm_delete_kb(abs_index)
        )
        return

    if q.data == "bdays:del_no":
        await q.edit_message_text("Отказано.", reply_markup=bdays_menu())
        return

    if q.data.startswith("bdays:del_yes:"):
        abs_index = int(q.data.split(":")[2])
        if abs_index < 0 or abs_index >= len(data["birthdays"]):
            await q.edit_message_text("❌ Невалиден избор.", reply_markup=bdays_menu())
            return
        it = data["birthdays"].pop(abs_index)
        save_data(data)
        await q.edit_message_text(
            f"✅ Изтрих: {it.get('name','—')} — {it.get('date','—')}",
            reply_markup=bdays_menu()
        )
        return

    if q.data.startswith("bdays:edit_abs:"):
        abs_index = int(q.data.split(":")[2])
        if abs_index < 0 or abs_index >= len(data["birthdays"]):
            await q.edit_message_text("❌ Невалиден избор.", reply_markup=bdays_menu())
            return

        it = data["birthdays"][abs_index]
        context.chat_data.clear()
        context.chat_data["mode"] = "bday_edit_choose"
        context.chat_data["bday_edit_index"] = abs_index

        await q.edit_message_text(
            f"✏️ Редакция\n\n🎂 {it.get('name','—')}\n📅 {it.get('date','—')}\n\nКакво искаш да промениш?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✏️ Име", callback_data="bdays:edit_name"),
                 InlineKeyboardButton("📅 Дата", callback_data="bdays:edit_date")],
                [InlineKeyboardButton("⬅️ Назад", callback_data="bdays:show_buttons")]
            ])
        )
        return

    if q.data == "bdays:edit_name":
        if context.chat_data.get("mode") != "bday_edit_choose":
            await q.edit_message_text("❌ Няма активна редакция.", reply_markup=bdays_menu())
            return
        context.chat_data["mode"] = "bday_edit_name"
        await q.edit_message_text("✍️ Напиши новото ИМЕ:")
        return

    if q.data == "bdays:edit_date":
        if context.chat_data.get("mode") != "bday_edit_choose":
            await q.edit_message_text("❌ Няма активна редакция.", reply_markup=bdays_menu())
            return
        context.chat_data["mode"] = "bday_edit_date"
        await q.edit_message_text("✍️ Напиши новата ДАТА (пример: 24.01 или 24.01.1995):")
        return

    if q.data == "bdays:next":
        upcoming = []
        for b in data["birthdays"]:
            parsed = parse_bday(b.get("date", ""))
            if not parsed:
                continue
            d, m = parsed
            left, next_dt = days_until_birthday(d, m)
            upcoming.append((left, b.get("name", "—"), b.get("date", "—"), next_dt))

        if not upcoming:
            await q.edit_message_text("❌ Няма валидни дати за рождени дни.", reply_markup=bdays_menu())
            return

        upcoming.sort(key=lambda x: x[0])
        left, name, dstr, next_dt = upcoming[0]
        text = (
            "⭐ Следващ рожден ден:\n"
            f"🎉 {name}\n"
            f"📅 Дата: {dstr}\n"
            f"⏳ Остават {left} дни\n"
            f"➡️ На: {next_dt.strftime('%d.%m.%Y')}"
        )
        await q.edit_message_text(text, reply_markup=bdays_menu())
        return

    if q.data == "bdays:clear":
        data["birthdays"] = []
        save_data(data)
        await q.edit_message_text("🧹 Изчистих всички рождени дни.", reply_markup=bdays_menu())
        return

    # -------- TASKS --------
    if q.data == "tasks:show":
        if not data["tasks"]:
            await q.edit_message_text("✅ Няма задачи.", reply_markup=tasks_menu())
            return

        view_tasks = data["tasks"][-30:]
        offset = len(data["tasks"]) - len(view_tasks)

        lines = ["✅ Активни задачи (последните 30):"]
        for i, t in enumerate(view_tasks, 1):
            txt = t.get("text", "—")
            d = t.get("date", "")
            if d:
                extra = days_left_text(d)
                lines.append(f"{i}. {txt} — {d}" + (f" • {extra}" if extra else ""))
            else:
                lines.append(f"{i}. {txt}")

        lines.append("\nНатисни ✔️ бутона под задачата, за да я отметнеш като изпълнена.")
        await q.edit_message_text("\n".join(lines), reply_markup=tasks_show_keyboard(view_tasks, offset))
        return

    if q.data == "tasks:upcoming":
        items = []
        for t in data["tasks"]:
            d = t.get("date", "")
            dt = parse_bg_date_full(d) if d else None
            if dt:
                items.append((dt, t.get("text", "—"), d))
        if not items:
            await q.edit_message_text("📅 Няма задачи с валидна дата (ДД.ММ.ГГГГ).", reply_markup=tasks_menu())
            return

        items.sort(key=lambda x: x[0])
        lines = ["📅 Предстоящи задачи:"]
        for dt, txt, dstr in items[:30]:
            extra = days_left_text(dstr)
            lines.append(f"• {txt} — {dstr}" + (f" • {extra}" if extra else ""))
        await q.edit_message_text("\n".join(lines), reply_markup=tasks_menu())
        return

    if q.data == "tasks:add":
        context.chat_data["mode"] = "task_text"
        await q.edit_message_text("➕ Добавяне на задача\n\nНапиши задачата (пример: Смени гуми):")
        return

    if q.data == "tasks:clear":
        data["tasks"] = []
        save_data(data)
        await q.edit_message_text("🧹 Изчистих всички активни задачи.", reply_markup=tasks_menu())
        return

    if q.data.startswith("tasks:done_abs:"):
        abs_index = int(q.data.split(":")[2])
        tasks = data["tasks"]
        if abs_index < 0 or abs_index >= len(tasks):
            await q.edit_message_text("❌ Невалиден избор.", reply_markup=tasks_menu())
            return

        task = tasks.pop(abs_index)
        task["done_at"] = date.today().strftime("%d.%m.%Y")
        data["tasks_done"].append(task)
        save_data(data)

        await q.edit_message_text(
            f"✅ Отметната като изпълнена:\n• {task.get('text','—')}\n📅 Дата: {task.get('date','—') or '—'}\n✔️ Изпълнена на: {task['done_at']}",
            reply_markup=tasks_menu()
        )
        return

    if q.data == "tasks:done_pick":
        if not data["tasks"]:
            await q.edit_message_text("✅ Няма активни задачи.", reply_markup=tasks_menu())
            return
        await q.edit_message_text("✔️ Избери задача, която е изпълнена:", reply_markup=tasks_pick_keyboard(data["tasks"]))
        return

    if q.data.startswith("tasks:done:"):
        pick = int(q.data.split(":")[2])
        tasks = data["tasks"]
        if pick < 1 or pick > min(30, len(tasks)):
            await q.edit_message_text("❌ Невалиден избор.", reply_markup=tasks_menu())
            return

        task = tasks.pop(pick - 1)
        task["done_at"] = date.today().strftime("%d.%m.%Y")
        data["tasks_done"].append(task)
        save_data(data)

        await q.edit_message_text(
            f"✅ Отметната като изпълнена:\n• {task.get('text','—')}\n📅 Дата: {task.get('date','—') or '—'}\n✔️ Изпълнена на: {task['done_at']}",
            reply_markup=tasks_menu()
        )
        return

    if q.data == "tasks:history":
        done = data.get("tasks_done", [])
        if not done:
            await q.edit_message_text("📜 Историята е празна.", reply_markup=tasks_menu())
            return

        lines = ["📜 История (последните 30):"]
        for i, t in enumerate(done[-30:], 1):
            txt = t.get("text", "—")
            d = t.get("date", "")
            done_at = t.get("done_at", "—")
            line = f"{i}. {txt}"
            if d:
                line += f" — {d}"
            line += f"  ✔️ {done_at}"
            lines.append(line)

        await q.edit_message_text("\n".join(lines), reply_markup=tasks_menu())
        return

    if q.data == "tasks:history_clear":
        data["tasks_done"] = []
        save_data(data)
        await q.edit_message_text("🧹 Изчистих историята.", reply_markup=tasks_menu())
        return

    # -------- ORDERS --------
    if q.data == "orders:list":
        suppliers = data["orders"]["suppliers"]
        if not suppliers:
            await q.edit_message_text("📦 Няма добавени доставчици.", reply_markup=orders_menu())
            return

        lines = ["📦 Доставчици:"]
        for i, s in enumerate(suppliers, 1):
            days = ", ".join(s.get("days", [])) or "—"
            lines.append(f"{i}. {s.get('name','—')} → {days}")
        await q.edit_message_text("\n".join(lines), reply_markup=orders_menu())
        return

    if q.data == "orders:clear":
        data["orders"]["suppliers"] = []
        save_data(data)
        await q.edit_message_text("🧹 Изчистих всички доставчици.", reply_markup=orders_menu())
        return

    if q.data == "orders:add":
        context.chat_data.clear()
        context.chat_data["mode"] = "orders_supplier_name"
        await q.edit_message_text("➕ Добавяне на доставчик\n\nНапиши ИМЕ на доставчика (пример: Econt):")
        return

    if q.data == "orders:check":
        context.chat_data.clear()
        context.chat_data["mode"] = "orders_check"
        await q.edit_message_text("🔎 Провери доставчик\n\nНапиши ИМЕ или НОМЕР от списъка (пример: 2):")
        return

    if q.data == "orders:edit":
        suppliers = data["orders"]["suppliers"]
        if not suppliers:
            await q.edit_message_text("📦 Няма доставчици за редакция.", reply_markup=orders_menu())
            return
        await q.edit_message_text("✏️ Редакция на доставчик\n\nИзбери доставчик:", reply_markup=orders_pick_supplier_keyboard(suppliers))
        return

    if q.data.startswith("orders:edit_pick:"):
        suppliers = data["orders"]["suppliers"]
        idx = int(q.data.split(":")[2])
        if idx < 1 or idx > len(suppliers):
            await q.edit_message_text("❌ Невалиден избор.", reply_markup=orders_menu())
            return

        supplier = suppliers[idx - 1]
        name = supplier.get("name", "—")
        current_days = set(supplier.get("days", []))

        context.chat_data["orders_edit_index"] = idx - 1
        context.chat_data["orders_supplier_name_tmp"] = name
        context.chat_data["orders_days_selected"] = list(current_days)

        msg = (
            "📦 Редакция на дни за доставка\n"
            f"Доставчик: {name}\n"
            f"Избрани дни: {selected_days_text(current_days)}\n\n"
            "Натискай дните, после ✅ Готово."
        )
        await q.edit_message_text(msg, reply_markup=orders_days_keyboard(current_days))
        return

    if q.data.startswith("orders:day:"):
        idx = int(q.data.split(":")[2])
        selected = set(context.chat_data.get("orders_days_selected", []))
        _, full = DAYS[idx]
        if full in selected:
            selected.remove(full)
        else:
            selected.add(full)
        context.chat_data["orders_days_selected"] = list(selected)

        name = context.chat_data.get("orders_supplier_name_tmp", "—")
        msg = (
            "📦 Избор/Редакция на дни за доставка\n"
            f"Доставчик: {name}\n"
            f"Избрани дни: {selected_days_text(selected)}\n\n"
            "Натискай дните, после ✅ Готово."
        )
        await q.edit_message_text(msg, reply_markup=orders_days_keyboard(selected))
        return

    if q.data == "orders:days_clear":
        context.chat_data["orders_days_selected"] = []
        name = context.chat_data.get("orders_supplier_name_tmp", "—")
        selected = set()
        msg = (
            "📦 Избор/Редакция на дни за доставка\n"
            f"Доставчик: {name}\n"
            f"Избрани дни: {selected_days_text(selected)}\n\n"
            "Натискай дните, после ✅ Готово."
        )
        await q.edit_message_text(msg, reply_markup=orders_days_keyboard(selected))
        return

    if q.data == "orders:days_cancel":
        context.chat_data.clear()
        await q.edit_message_text("Отказано.", reply_markup=orders_menu())
        return

    if q.data == "orders:days_done":
        name = (context.chat_data.get("orders_supplier_name_tmp") or "").strip()
        selected = set(context.chat_data.get("orders_days_selected", []))

        if not name:
            context.chat_data.clear()
            await q.edit_message_text("❌ Грешка: няма име на доставчик.", reply_markup=orders_menu())
            return

        if not selected:
            await q.edit_message_text("❌ Избери поне 1 ден.", reply_markup=orders_days_keyboard(selected))
            return

        ordered_days = [full for _, full in DAYS if full in selected]
        suppliers = data["orders"]["suppliers"]

        edit_index = context.chat_data.get("orders_edit_index", None)
        if isinstance(edit_index, int) and 0 <= edit_index < len(suppliers):
            suppliers[edit_index]["days"] = ordered_days
            save_data(data)
            context.chat_data.clear()
            await q.edit_message_text(
                f"✅ Обнових доставчик: {name}\n📅 Дни: {', '.join(ordered_days)}",
                reply_markup=orders_menu()
            )
            return

        lower = name.lower()
        updated = False
        for s in suppliers:
            if s.get("name", "").strip().lower() == lower:
                s["days"] = ordered_days
                updated = True
                break
        if not updated:
            suppliers.append({"name": name, "days": ordered_days})

        save_data(data)
        context.chat_data.clear()
        await q.edit_message_text(
            f"✅ Запаметих доставчик: {name}\n📅 Дни: {', '.join(ordered_days)}",
            reply_markup=orders_menu()
        )
        return


# =========================
# TEXT INPUT
# =========================
async def text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        return

    data = load_data()
    mode = context.chat_data.get("mode")

    # SETTINGS: set city
    if mode == "set_city":
        city = text.strip()
        if len(city) < 2:
            await update.message.reply_text("❌ Невалиден град. Пример: Sofia,BG")
            return
        data["settings"]["city"] = city
        save_data(data)
        context.chat_data.clear()
        await update.message.reply_text(f"✅ Запаметих град: {city}", reply_markup=settings_menu(data))
        return

    # CAR edit
    if mode == "car_edit":
        field = context.chat_data.get("car_field")
        if field:
            data["car"][field] = text
            save_data(data)
        context.chat_data.clear()
        await update.message.reply_text("✅ Запаметено!\n\n" + car_summary(data), reply_markup=car_menu())
        return

    # BDAY add
    if mode == "bday_name":
        context.chat_data["mode"] = "bday_date"
        context.chat_data["bday_name"] = text
        await update.message.reply_text("Сега напиши ДАТА (пример: 24.01 или 24.01.1995):")
        return

    if mode == "bday_date":
        name = context.chat_data.get("bday_name", "—")
        data["birthdays"].append({"name": name, "date": text})
        save_data(data)
        context.chat_data.clear()
        await update.message.reply_text("✅ Добавено!", reply_markup=bdays_menu())
        return

    # BDAY edit name/date
    if mode == "bday_edit_name":
        idx = context.chat_data.get("bday_edit_index")
        if isinstance(idx, int) and 0 <= idx < len(data["birthdays"]):
            data["birthdays"][idx]["name"] = text
            save_data(data)
            context.chat_data.clear()
            await update.message.reply_text("✅ Името е обновено!", reply_markup=bdays_menu())
            return

    if mode == "bday_edit_date":
        idx = context.chat_data.get("bday_edit_index")
        if isinstance(idx, int) and 0 <= idx < len(data["birthdays"]):
            data["birthdays"][idx]["date"] = text
            save_data(data)
            context.chat_data.clear()
            await update.message.reply_text("✅ Датата е обновена!", reply_markup=bdays_menu())
            return

    # TASK add
    if mode == "task_text":
        context.chat_data["mode"] = "task_date"
        context.chat_data["task_text"] = text
        await update.message.reply_text("Напиши дата (ДД.ММ.ГГГГ) или '-' ако няма дата:")
        return

    if mode == "task_date":
        task_text = context.chat_data.get("task_text", "—")
        task_date = "" if text == "-" else text
        data["tasks"].append({"text": task_text, "date": task_date})
        save_data(data)
        context.chat_data.clear()
        await update.message.reply_text("✅ Задачата е добавена!", reply_markup=tasks_menu())
        return

    # ORDERS add name -> day picker
    if mode == "orders_supplier_name":
        name = text.strip()
        context.chat_data.clear()
        context.chat_data["orders_supplier_name_tmp"] = name
        context.chat_data["orders_days_selected"] = []
        await update.message.reply_text(
            f"📦 Избор на дни за доставка\nДоставчик: {name}\nИзбрани дни: —\n\nНатискай дните, после ✅ Готово.",
            reply_markup=orders_days_keyboard(set())
        )
        return

    # ORDERS check by name/number
    if mode == "orders_check":
        suppliers = data["orders"]["suppliers"]
        if not suppliers:
            context.chat_data.clear()
            await update.message.reply_text("📦 Няма доставчици.", reply_markup=orders_menu())
            return

        query = text.strip()
        found = None

        if query.isdigit():
            idx = int(query)
            if 1 <= idx <= len(suppliers):
                found = suppliers[idx - 1]
        else:
            ql = query.lower()
            for s in suppliers:
                if s.get("name", "").lower() == ql:
                    found = s
                    break

        if not found:
            await update.message.reply_text("❌ Не намерих доставчик. Пиши точните ИМЕ или НОМЕР.")
            return

        days = ", ".join(found.get("days", [])) or "—"
        context.chat_data.clear()
        await update.message.reply_text(
            f"📦 {found.get('name','—')}\n📅 Дни за доставка: {days}",
            reply_markup=orders_menu()
        )
        return

    # fallback
    await update.message.reply_text("Напиши /start (или /stat) и използвай бутоните 🙂")


# =========================
# MAIN
# =========================
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stat", start))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input))
    app.run_polling()


if __name__ == "__main__":
    main()
