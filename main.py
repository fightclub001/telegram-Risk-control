import asyncio
import json
import os
import time
import hashlib
from collections import deque
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ChatPermissions, ReplyKeyboardRemove
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ==================== 配置 ====================
GROUP_IDS = set()
ADMIN_IDS = set()

try:
    for gid in os.getenv("GROUP_IDS", "").strip().split():
        if gid.strip(): 
            GROUP_IDS.add(int(gid.strip()))
    for uid in os.getenv("ADMIN_IDS", "").strip().split():
        if uid.strip(): 
            ADMIN_IDS.add(int(uid.strip()))
    if not GROUP_IDS or not ADMIN_IDS:
        raise ValueError("GROUP_IDS 或 ADMIN_IDS 为空")
except Exception as e:
    raise ValueError(f"❌ 环境变量错误: {e}")

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("❌ 请设置 BOT_TOKEN")

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# ==================== 数据文件配置 ====================
os.makedirs("/data", exist_ok=True)
DATA_FILE = "/data/reports.json"
CONFIG_FILE = "/data/config.json"

reports = {}
lock = asyncio.Lock()

# ==================== 全局配置结构 ====================
DEFAULT_CONFIG = {
    "groups": {}
}

config = DEFAULT_CONFIG.copy()

# ==================== 配置管理 ====================
async def load_config():
    global config
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
        else:
            config = DEFAULT_CONFIG.copy()
            await save_config()
    except Exception as e:
        print(f"加载配置失败: {e}")
        config = DEFAULT_CONFIG.copy()

async def save_config():
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存配置失败: {e}")

def get_group_config(group_id: int):
    """获取群组配置，不存在则创建默认配置"""
    gid = str(group_id)
    if gid not in config["groups"]:
        config["groups"][gid] = {
            "name": f"群组-{group_id}",
            "enabled": True,
            
            # 简介检测
            "bio_keywords": ["qq:", "qq：", "qq号", "加qq", "扣扣", "微信", "wx:", "weixin", "加我微信", "wxid_", "幼女", "萝莉", "少妇", "人妻", "福利", "约炮", "onlyfans", "小红书", "抖音", "纸飞机", "机场", "t.me/", "@"],
            "check_bio_link": True,
            "check_bio_keywords": True,
            
            # 显示名称检测
            "display_keywords": ["加v", "加微信", "加qq", "加扣", "福利加", "约", "约炮", "资源私聊", "私我", "私聊我", "飞机", "纸飞机", "福利", "外围", "反差", "嫩模", "学生妹", "空姐", "人妻", "熟女", "onlyfans", "of", "leak", "nudes", "十八+", "av"],
            "check_display_keywords": True,
            
            # 短消息检测
            "short_msg_detection": True,
            "short_msg_threshold": 3,
            "min_consecutive_count": 2,
            "time_window_seconds": 60,
            
            # 填充垃圾检测
            "fill_garbage_detection": True,
            "fill_garbage_min_raw_len": 12,
            "fill_garbage_max_clean_len": 8,
            "fill_space_ratio": 0.30,
            
            # 自动回复
            "autoreply": {
                "enabled": False,
                "keywords": [],
                "reply_text": "",
                "buttons": [],
                "delete_user_sec": 0,
                "delete_bot_sec": 0
            },
            
            # 豁免用户
            "exempt_users": {}
        }
    return config["groups"][gid]

# ==================== FSM 状态 ====================
class AdminStates(StatesGroup):
    MainMenu = State()
    ChooseGroup = State()
    GroupMenu = State()
    EditBioKeywords = State()
    EditDisplayKeywords = State()
    EditAutoreplyKeywords = State()
    EditAutoreplyText = State()
    EditAutoreplyButtons = State()
    EditAutoreplyDeleteTime = State()
    EditShortMsgThreshold = State()
    EditConsecutiveCount = State()
    EditTimeWindow = State()
    EditFillGarbageMinRaw = State()
    EditFillGarbageMaxClean = State()
    EditFillSpaceRatio = State()

# ==================== UI 键盘 ====================
def get_main_menu_keyboard():
    buttons = [
        [InlineKeyboardButton(text="⚙️ 群组管理", callback_data="choose_group")],
        [InlineKeyboardButton(text="📊 状态查看", callback_data="view_status")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_group_list_keyboard():
    buttons = []
    for gid in sorted(GROUP_IDS):
        buttons.append([InlineKeyboardButton(text=f"👥 群组 {gid}", callback_data=f"select_group:{gid}")])
    buttons.append([InlineKeyboardButton(text="⬅️ 返回主菜单", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_group_menu_keyboard(group_id: int):
    buttons = [
        [InlineKeyboardButton(text="🔍 简介检测设置", callback_data=f"submenu_bio:{group_id}")],
        [InlineKeyboardButton(text="👤 显示名称检测", callback_data=f"submenu_display:{group_id}")],
        [InlineKeyboardButton(text="💬 短消息检测", callback_data=f"submenu_short:{group_id}")],
        [InlineKeyboardButton(text="🗑️ 填充垃圾检测", callback_data=f"submenu_fill:{group_id}")],
        [InlineKeyboardButton(text="🤖 自动回复设置", callback_data=f"submenu_autoreply:{group_id}")],
        [InlineKeyboardButton(text="🎛️ 群组基础设置", callback_data=f"submenu_basic:{group_id}")],
        [InlineKeyboardButton(text="⬅️ 返回选择", callback_data="back_choose_group")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_bio_menu_keyboard(group_id: int):
    cfg = get_group_config(group_id)
    link_status = "✅" if cfg.get("check_bio_link") else "❌"
    kw_status = "✅" if cfg.get("check_bio_keywords") else "❌"
    buttons = [
        [InlineKeyboardButton(text=f"检测链接 {link_status}", callback_data=f"toggle_bio_link:{group_id}")],
        [InlineKeyboardButton(text=f"检测敏感词 {kw_status}", callback_data=f"toggle_bio_keywords:{group_id}")],
        [InlineKeyboardButton(text="📋 编辑敏感词列表", callback_data=f"edit_bio_kw:{group_id}")],
        [InlineKeyboardButton(text="👀 查看敏感词", callback_data=f"view_bio_kw:{group_id}")],
        [InlineKeyboardButton(text="⬅️ 返回群组菜单", callback_data=f"group_menu:{group_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_display_menu_keyboard(group_id: int):
    cfg = get_group_config(group_id)
    status = "✅" if cfg.get("check_display_keywords") else "❌"
    buttons = [
        [InlineKeyboardButton(text=f"启用检测 {status}", callback_data=f"toggle_display:{group_id}")],
        [InlineKeyboardButton(text="📋 编辑敏感词列表", callback_data=f"edit_display_kw:{group_id}")],
        [InlineKeyboardButton(text="👀 查看敏感词", callback_data=f"view_display_kw:{group_id}")],
        [InlineKeyboardButton(text="⬅️ 返回群组菜单", callback_data=f"group_menu:{group_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_short_menu_keyboard(group_id: int):
    cfg = get_group_config(group_id)
    enabled = "✅" if cfg.get("short_msg_detection") else "❌"
    buttons = [
        [InlineKeyboardButton(text=f"启用检测 {enabled}", callback_data=f"toggle_short:{group_id}")],
        [InlineKeyboardButton(text=f"字数阈值: {cfg.get('short_msg_threshold')}", callback_data=f"edit_threshold:{group_id}")],
        [InlineKeyboardButton(text=f"连续条数: {cfg.get('min_consecutive_count')}", callback_data=f"edit_consecutive:{group_id}")],
        [InlineKeyboardButton(text=f"时间窗口: {cfg.get('time_window_seconds')}s", callback_data=f"edit_window:{group_id}")],
        [InlineKeyboardButton(text="⬅️ 返回群组菜单", callback_data=f"group_menu:{group_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_fill_menu_keyboard(group_id: int):
    cfg = get_group_config(group_id)
    enabled = "✅" if cfg.get("fill_garbage_detection") else "❌"
    buttons = [
        [InlineKeyboardButton(text=f"启用检测 {enabled}", callback_data=f"toggle_fill:{group_id}")],
        [InlineKeyboardButton(text=f"最小长度: {cfg.get('fill_garbage_min_raw_len')}", callback_data=f"edit_fill_min:{group_id}")],
        [InlineKeyboardButton(text=f"清理后长度: {cfg.get('fill_garbage_max_clean_len')}", callback_data=f"edit_fill_max:{group_id}")],
        [InlineKeyboardButton(text=f"空格比例: {cfg.get('fill_space_ratio'):.1%}", callback_data=f"edit_fill_ratio:{group_id}")],
        [InlineKeyboardButton(text="⬅️ 返回群组菜单", callback_data=f"group_menu:{group_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_autoreply_menu_keyboard(group_id: int):
    cfg = get_group_config(group_id)
    ar = cfg.get("autoreply", {})
    enabled = "✅" if ar.get("enabled") else "❌"
    buttons = [
        [InlineKeyboardButton(text=f"启用自动回复 {enabled}", callback_data=f"toggle_ar:{group_id}")],
        [InlineKeyboardButton(text="🔑 编辑关键词", callback_data=f"edit_ar_kw:{group_id}")],
        [InlineKeyboardButton(text="📝 编辑回复文本", callback_data=f"edit_ar_text:{group_id}")],
        [InlineKeyboardButton(text="🔘 编辑按钮", callback_data=f"edit_ar_btn:{group_id}")],
        [InlineKeyboardButton(text="⏱️ 编辑删除延时", callback_data=f"edit_ar_del:{group_id}")],
        [InlineKeyboardButton(text="⬅️ 返回群组菜单", callback_data=f"group_menu:{group_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_basic_menu_keyboard(group_id: int):
    cfg = get_group_config(group_id)
    enabled = "✅ 已启用" if cfg.get("enabled") else "❌ 已禁用"
    buttons = [
        [InlineKeyboardButton(text=f"群组状态: {enabled}", callback_data=f"toggle_group:{group_id}")],
        [InlineKeyboardButton(text="⬅️ 返回群组菜单", callback_data=f"group_menu:{group_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ==================== 管理员命令 ====================
@router.message(Command("admin"), F.from_user.id.in_(ADMIN_IDS))
async def admin_panel(message: Message, state: FSMContext):
    text = "👮 管理员控制面板\n\n请选择要执行的操作："
    kb = get_main_menu_keyboard()
    await message.reply(text, reply_markup=kb)
    await state.set_state(AdminStates.MainMenu)

# ==================== 主菜单 ====================
@router.callback_query(F.data == "choose_group", F.from_user.id.in_(ADMIN_IDS))
async def choose_group_callback(callback: CallbackQuery, state: FSMContext):
    text = "📋 选择要管理的群组："
    kb = get_group_list_keyboard()
    await callback.message.edit_text(text, reply_markup=kb)
    await state.set_state(AdminStates.ChooseGroup)
    await callback.answer()

@router.callback_query(F.data.startswith("select_group:"), F.from_user.id.in_(ADMIN_IDS))
async def select_group(callback: CallbackQuery, state: FSMContext):
    try:
        group_id = int(callback.data.split(":", 1)[1])
        cfg = get_group_config(group_id)
        await state.update_data(group_id=group_id)
        text = f"👥 群组 {group_id} - {cfg.get('name')}\n\n选择要配置的项目："
        kb = get_group_menu_keyboard(group_id)
        await callback.message.edit_text(text, reply_markup=kb)
        await state.set_state(AdminStates.GroupMenu)
        await callback.answer()
    except Exception as e:
        await callback.answer(f"❌ 错误: {str(e)}", show_alert=True)

@router.callback_query(F.data == "back_main", F.from_user.id.in_(ADMIN_IDS))
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    text = "👮 管理员控制面板\n\n请选择要执行的操作："
    kb = get_main_menu_keyboard()
    await callback.message.edit_text(text, reply_markup=kb)
    await state.set_state(AdminStates.MainMenu)
    await callback.answer()

@router.callback_query(F.data == "back_choose_group", F.from_user.id.in_(ADMIN_IDS))
async def back_to_choose_group(callback: CallbackQuery, state: FSMContext):
    text = "📋 选择要管理的群组："
    kb = get_group_list_keyboard()
    await callback.message.edit_text(text, reply_markup=kb)
    await state.set_state(AdminStates.ChooseGroup)
    await callback.answer()

# ==================== 简介检测菜单 ====================
@router.callback_query(F.data.startswith("submenu_bio:"), F.from_user.id.in_(ADMIN_IDS))
async def bio_submenu(callback: CallbackQuery, state: FSMContext):
    try:
        group_id = int(callback.data.split(":", 1)[1])
        cfg = get_group_config(group_id)
        link_status = "✅" if cfg.get("check_bio_link") else "❌"
        kw_status = "✅" if cfg.get("check_bio_keywords") else "❌"
        text = f"🔍 简介检测设置\n\n当前状态：\n• 链接检测: {link_status}\n• 敏感词检测: {kw_status}"
        kb = get_bio_menu_keyboard(group_id)
        await callback.message.edit_text(text, reply_markup=kb)
        await callback.answer()
    except Exception as e:
        await callback.answer(f"❌ 错误: {str(e)}", show_alert=True)

@router.callback_query(F.data.startswith("toggle_bio_link:"), F.from_user.id.in_(ADMIN_IDS))
async def toggle_bio_link(callback: CallbackQuery):
    try:
        group_id = int(callback.data.split(":", 1)[1])
        cfg = get_group_config(group_id)
        cfg["check_bio_link"] = not cfg.get("check_bio_link", True)
        await save_config()
        status = "✅ 已启用" if cfg["check_bio_link"] else "❌ 已禁用"
        await callback.answer(f"简介链接检测: {status}", show_alert=True)
        kb = get_bio_menu_keyboard(group_id)
        link_status = "✅" if cfg.get("check_bio_link") else "❌"
        kw_status = "✅" if cfg.get("check_bio_keywords") else "❌"
        text = f"🔍 简介检测设置\n\n当前状态：\n• 链接检测: {link_status}\n• 敏感词检测: {kw_status}"
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception as e:
        await callback.answer(f"❌ 错误: {str(e)}", show_alert=True)

@router.callback_query(F.data.startswith("toggle_bio_keywords:"), F.from_user.id.in_(ADMIN_IDS))
async def toggle_bio_keywords(callback: CallbackQuery):
    try:
        group_id = int(callback.data.split(":", 1)[1])
        cfg = get_group_config(group_id)
        cfg["check_bio_keywords"] = not cfg.get("check_bio_keywords", True)
        await save_config()
        status = "✅ 已启用" if cfg["check_bio_keywords"] else "❌ 已禁用"
        await callback.answer(f"简介敏感词检测: {status}", show_alert=True)
        kb = get_bio_menu_keyboard(group_id)
        link_status = "✅" if cfg.get("check_bio_link") else "❌"
        kw_status = "✅" if cfg.get("check_bio_keywords") else "❌"
        text = f"🔍 简介检测设置\n\n当前状态：\n• 链接检测: {link_status}\n• 敏感词检测: {kw_status}"
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception as e:
        await callback.answer(f"❌ 错误: {str(e)}", show_alert=True)

@router.callback_query(F.data.startswith("edit_bio_kw:"), F.from_user.id.in_(ADMIN_IDS))
async def edit_bio_keywords(callback: CallbackQuery, state: FSMContext):
    try:
        group_id = int(callback.data.split(":", 1)[1])
        cfg = get_group_config(group_id)
        keywords = cfg.get("bio_keywords", [])
        kw_text = "\n".join(keywords)
        text = f"📝 编辑简介敏感词\n\n当前词汇：\n{kw_text}\n\n请发送新的关键词列表（一行一个），或发送 /clear 清空："
        await callback.message.edit_text(text, reply_markup=None)
        await state.update_data(group_id=group_id, current_menu="bio_kw")
        await state.set_state(AdminStates.EditBioKeywords)
        await callback.answer()
    except Exception as e:
        await callback.answer(f"❌ 错误: {str(e)}", show_alert=True)

@router.message(StateFilter(AdminStates.EditBioKeywords), F.from_user.id.in_(ADMIN_IDS))
async def process_bio_keywords(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        group_id = data.get("group_id")
        cfg = get_group_config(group_id)
        
        if message.text.strip() == "/clear":
            cfg["bio_keywords"] = []
        else:
            cfg["bio_keywords"] = [x.strip().lower() for x in message.text.strip().split("\n") if x.strip()]
        
        await save_config()
        kb = get_bio_menu_keyboard(group_id)
        await message.reply(f"✅ 简介敏感词已更新（共 {len(cfg['bio_keywords'])} 个）", reply_markup=kb)
        await state.set_state(AdminStates.GroupMenu)
    except Exception as e:
        await message.reply(f"❌ 错误: {str(e)}")

@router.callback_query(F.data.startswith("view_bio_kw:"), F.from_user.id.in_(ADMIN_IDS))
async def view_bio_keywords(callback: CallbackQuery):
    try:
        group_id = int(callback.data.split(":", 1)[1])
        cfg = get_group_config(group_id)
        keywords = cfg.get("bio_keywords", [])
        if keywords:
            kw_text = "\n".join(keywords)
            text = f"📋 简介敏感词列表（共 {len(keywords)} 个）：\n\n{kw_text}"
        else:
            text = "📋 暂无敏感词"
        await callback.answer(text, show_alert=True)
    except Exception as e:
        await callback.answer(f"❌ 错误: {str(e)}", show_alert=True)

@router.callback_query(F.data.startswith("group_menu:"), F.from_user.id.in_(ADMIN_IDS))
async def back_to_group_menu(callback: CallbackQuery, state: FSMContext):
    try:
        group_id = int(callback.data.split(":", 1)[1])
        cfg = get_group_config(group_id)
        await state.update_data(group_id=group_id)
        text = f"👥 群组 {group_id} - {cfg.get('name')}\n\n选择要配置的项目："
        kb = get_group_menu_keyboard(group_id)
        await callback.message.edit_text(text, reply_markup=kb)
        await state.set_state(AdminStates.GroupMenu)
        await callback.answer()
    except Exception as e:
        await callback.answer(f"❌ 错误: {str(e)}", show_alert=True)

# ==================== 显示名称检测菜单 ====================
@router.callback_query(F.data.startswith("submenu_display:"), F.from_user.id.in_(ADMIN_IDS))
async def display_submenu(callback: CallbackQuery, state: FSMContext):
    try:
        group_id = int(callback.data.split(":", 1)[1])
        cfg = get_group_config(group_id)
        status = "✅" if cfg.get("check_display_keywords") else "❌"
        text = f"👤 显示名称检测设置\n\n当前状态：{status}"
        kb = get_display_menu_keyboard(group_id)
        await callback.message.edit_text(text, reply_markup=kb)
        await callback.answer()
    except Exception as e:
        await callback.answer(f"❌ 错误: {str(e)}", show_alert=True)

@router.callback_query(F.data.startswith("toggle_display:"), F.from_user.id.in_(ADMIN_IDS))
async def toggle_display(callback: CallbackQuery):
    try:
        group_id = int(callback.data.split(":", 1)[1])
        cfg = get_group_config(group_id)
        cfg["check_display_keywords"] = not cfg.get("check_display_keywords", True)
        await save_config()
        status = "✅ 已启用" if cfg["check_display_keywords"] else "❌ 已禁用"
        await callback.answer(f"显示名称检测: {status}", show_alert=True)
        kb = get_display_menu_keyboard(group_id)
        status_display = "✅" if cfg.get("check_display_keywords") else "❌"
        text = f"👤 显示名称检测设置\n\n当前状态：{status_display}"
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception as e:
        await callback.answer(f"❌ 错误: {str(e)}", show_alert=True)

@router.callback_query(F.data.startswith("edit_display_kw:"), F.from_user.id.in_(ADMIN_IDS))
async def edit_display_keywords(callback: CallbackQuery, state: FSMContext):
    try:
        group_id = int(callback.data.split(":", 1)[1])
        cfg = get_group_config(group_id)
        keywords = cfg.get("display_keywords", [])
        kw_text = "\n".join(keywords)
        text = f"📝 编辑显示名称敏感词\n\n当前词汇：\n{kw_text}\n\n请发送新的关键词列表（一行一个），或发送 /clear 清空："
        await callback.message.edit_text(text, reply_markup=None)
        await state.update_data(group_id=group_id)
        await state.set_state(AdminStates.EditDisplayKeywords)
        await callback.answer()
    except Exception as e:
        await callback.answer(f"❌ 错误: {str(e)}", show_alert=True)

@router.message(StateFilter(AdminStates.EditDisplayKeywords), F.from_user.id.in_(ADMIN_IDS))
async def process_display_keywords(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        group_id = data.get("group_id")
        cfg = get_group_config(group_id)
        
        if message.text.strip() == "/clear":
            cfg["display_keywords"] = []
        else:
            cfg["display_keywords"] = [x.strip().lower() for x in message.text.strip().split("\n") if x.strip()]
        
        await save_config()
        kb = get_display_menu_keyboard(group_id)
        await message.reply(f"✅ 显示名称敏感词已更新（共 {len(cfg['display_keywords'])} 个）", reply_markup=kb)
        await state.set_state(AdminStates.GroupMenu)
    except Exception as e:
        await message.reply(f"❌ 错误: {str(e)}")

@router.callback_query(F.data.startswith("view_display_kw:"), F.from_user.id.in_(ADMIN_IDS))
async def view_display_keywords(callback: CallbackQuery):
    try:
        group_id = int(callback.data.split(":", 1)[1])
        cfg = get_group_config(group_id)
        keywords = cfg.get("display_keywords", [])
        if keywords:
            kw_text = "\n".join(keywords)
            text = f"📋 显示名称敏感词列表（共 {len(keywords)} 个）：\n\n{kw_text}"
        else:
            text = "📋 暂无敏感词"
        await callback.answer(text, show_alert=True)
    except Exception as e:
        await callback.answer(f"❌ 错误: {str(e)}", show_alert=True)

# ==================== 短消息检测菜单 ====================
@router.callback_query(F.data.startswith("submenu_short:"), F.from_user.id.in_(ADMIN_IDS))
async def short_submenu(callback: CallbackQuery, state: FSMContext):
    try:
        group_id = int(callback.data.split(":", 1)[1])
        cfg = get_group_config(group_id)
        enabled = "✅" if cfg.get("short_msg_detection") else "❌"
        text = f"💬 短消息检测设置\n\n当前状态：{enabled}\n• 字数阈值: {cfg.get('short_msg_threshold')}\n• 连续条数: {cfg.get('min_consecutive_count')}\n• 时间窗口: {cfg.get('time_window_seconds')}s"
        kb = get_short_menu_keyboard(group_id)
        await callback.message.edit_text(text, reply_markup=kb)
        await callback.answer()
    except Exception as e:
        await callback.answer(f"❌ 错误: {str(e)}", show_alert=True)

@router.callback_query(F.data.startswith("toggle_short:"), F.from_user.id.in_(ADMIN_IDS))
async def toggle_short_msg(callback: CallbackQuery):
    try:
        group_id = int(callback.data.split(":", 1)[1])
        cfg = get_group_config(group_id)
        cfg["short_msg_detection"] = not cfg.get("short_msg_detection", True)
        await save_config()
        status = "✅ 已启用" if cfg["short_msg_detection"] else "❌ 已禁用"
        await callback.answer(f"短消息检测: {status}", show_alert=True)
        kb = get_short_menu_keyboard(group_id)
        enabled = "✅" if cfg.get("short_msg_detection") else "❌"
        text = f"💬 短消息检测设置\n\n当前状态：{enabled}\n• 字数阈值: {cfg.get('short_msg_threshold')}\n• 连续条数: {cfg.get('min_consecutive_count')}\n• 时间窗口: {cfg.get('time_window_seconds')}s"
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception as e:
        await callback.answer(f"❌ 错误: {str(e)}", show_alert=True)

@router.callback_query(F.data.startswith("edit_threshold:"), F.from_user.id.in_(ADMIN_IDS))
async def edit_threshold(callback: CallbackQuery, state: FSMContext):
    try:
        group_id = int(callback.data.split(":", 1)[1])
        cfg = get_group_config(group_id)
        current = cfg.get("short_msg_threshold", 3)
        text = f"输入新的字数阈值（当前: {current}）："
        await callback.message.edit_text(text, reply_markup=None)
        await state.update_data(group_id=group_id, edit_field="short_msg_threshold")
        await state.set_state(AdminStates.EditShortMsgThreshold)
        await callback.answer()
    except Exception as e:
        await callback.answer(f"❌ 错误: {str(e)}", show_alert=True)

@router.message(StateFilter(AdminStates.EditShortMsgThreshold), F.from_user.id.in_(ADMIN_IDS))
async def process_threshold(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        group_id = data.get("group_id")
        cfg = get_group_config(group_id)
        value = int(message.text.strip())
        cfg["short_msg_threshold"] = value
        await save_config()
        kb = get_short_menu_keyboard(group_id)
        await message.reply(f"✅ 字数阈值已更新为 {value}", reply_markup=kb)
        await state.set_state(AdminStates.GroupMenu)
    except ValueError:
        await message.reply("❌ 请输入有效的数字")
    except Exception as e:
        await message.reply(f"❌ 错误: {str(e)}")

@router.callback_query(F.data.startswith("edit_consecutive:"), F.from_user.id.in_(ADMIN_IDS))
async def edit_consecutive(callback: CallbackQuery, state: FSMContext):
    try:
        group_id = int(callback.data.split(":", 1)[1])
        cfg = get_group_config(group_id)
        current = cfg.get("min_consecutive_count", 2)
        text = f"输入新的连续条数（当前: {current}）："
        await callback.message.edit_text(text, reply_markup=None)
        await state.update_data(group_id=group_id, edit_field="min_consecutive_count")
        await state.set_state(AdminStates.EditConsecutiveCount)
        await callback.answer()
    except Exception as e:
        await callback.answer(f"❌ 错误: {str(e)}", show_alert=True)

@router.message(StateFilter(AdminStates.EditConsecutiveCount), F.from_user.id.in_(ADMIN_IDS))
async def process_consecutive(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        group_id = data.get("group_id")
        cfg = get_group_config(group_id)
        value = int(message.text.strip())
        cfg["min_consecutive_count"] = value
        await save_config()
        kb = get_short_menu_keyboard(group_id)
        await message.reply(f"✅ 连续条数已更新为 {value}", reply_markup=kb)
        await state.set_state(AdminStates.GroupMenu)
    except ValueError:
        await message.reply("❌ 请输入有效的数字")
    except Exception as e:
        await message.reply(f"❌ 错误: {str(e)}")

@router.callback_query(F.data.startswith("edit_window:"), F.from_user.id.in_(ADMIN_IDS))
async def edit_window(callback: CallbackQuery, state: FSMContext):
    try:
        group_id = int(callback.data.split(":", 1)[1])
        cfg = get_group_config(group_id)
        current = cfg.get("time_window_seconds", 60)
        text = f"输入新的时间窗口（秒，当前: {current}）："
        await callback.message.edit_text(text, reply_markup=None)
        await state.update_data(group_id=group_id, edit_field="time_window_seconds")
        await state.set_state(AdminStates.EditTimeWindow)
        await callback.answer()
    except Exception as e:
        await callback.answer(f"❌ 错误: {str(e)}", show_alert=True)

@router.message(StateFilter(AdminStates.EditTimeWindow), F.from_user.id.in_(ADMIN_IDS))
async def process_window(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        group_id = data.get("group_id")
        cfg = get_group_config(group_id)
        value = int(message.text.strip())
        cfg["time_window_seconds"] = value
        await save_config()
        kb = get_short_menu_keyboard(group_id)
        await message.reply(f"✅ 时间窗口已更新为 {value} 秒", reply_markup=kb)
        await state.set_state(AdminStates.GroupMenu)
    except ValueError:
        await message.reply("❌ 请输入有效的数字")
    except Exception as e:
        await message.reply(f"❌ 错误: {str(e)}")

# ==================== 填充垃圾检测菜单 ====================
@router.callback_query(F.data.startswith("submenu_fill:"), F.from_user.id.in_(ADMIN_IDS))
async def fill_submenu(callback: CallbackQuery, state: FSMContext):
    try:
        group_id = int(callback.data.split(":", 1)[1])
        cfg = get_group_config(group_id)
        enabled = "✅" if cfg.get("fill_garbage_detection") else "❌"
        text = f"🗑️ 填充垃圾检测设置\n\n当前状态：{enabled}\n• 最小原始长度: {cfg.get('fill_garbage_min_raw_len')}\n• 清理后最大长度: {cfg.get('fill_garbage_max_clean_len')}\n• 空格比例阈值: {cfg.get('fill_space_ratio'):.1%}"
        kb = get_fill_menu_keyboard(group_id)
        await callback.message.edit_text(text, reply_markup=kb)
        await callback.answer()
    except Exception as e:
        await callback.answer(f"❌ 错误: {str(e)}", show_alert=True)

@router.callback_query(F.data.startswith("toggle_fill:"), F.from_user.id.in_(ADMIN_IDS))
async def toggle_fill(callback: CallbackQuery):
    try:
        group_id = int(callback.data.split(":", 1)[1])
        cfg = get_group_config(group_id)
        cfg["fill_garbage_detection"] = not cfg.get("fill_garbage_detection", True)
        await save_config()
        status = "✅ 已启用" if cfg["fill_garbage_detection"] else "❌ 已禁用"
        await callback.answer(f"填充垃圾检测: {status}", show_alert=True)
        kb = get_fill_menu_keyboard(group_id)
        enabled = "✅" if cfg.get("fill_garbage_detection") else "❌"
        text = f"🗑️ 填充垃圾检测设置\n\n当前状态：{enabled}\n• 最小原始长度: {cfg.get('fill_garbage_min_raw_len')}\n• 清理后最大长度: {cfg.get('fill_garbage_max_clean_len')}\n• 空格比例阈值: {cfg.get('fill_space_ratio'):.1%}"
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception as e:
        await callback.answer(f"❌ 错误: {str(e)}", show_alert=True)

@router.callback_query(F.data.startswith("edit_fill_min:"), F.from_user.id.in_(ADMIN_IDS))
async def edit_fill_min(callback: CallbackQuery, state: FSMContext):
    try:
        group_id = int(callback.data.split(":", 1)[1])
        cfg = get_group_config(group_id)
        current = cfg.get("fill_garbage_min_raw_len", 12)
        text = f"输入最小原始长度（当前: {current}）："
        await callback.message.edit_text(text, reply_markup=None)
        await state.update_data(group_id=group_id)
        await state.set_state(AdminStates.EditFillGarbageMinRaw)
        await callback.answer()
    except Exception as e:
        await callback.answer(f"❌ 错误: {str(e)}", show_alert=True)

@router.message(StateFilter(AdminStates.EditFillGarbageMinRaw), F.from_user.id.in_(ADMIN_IDS))
async def process_fill_min(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        group_id = data.get("group_id")
        cfg = get_group_config(group_id)
        value = int(message.text.strip())
        cfg["fill_garbage_min_raw_len"] = value
        await save_config()
        kb = get_fill_menu_keyboard(group_id)
        await message.reply(f"✅ 最小原始长度已更新为 {value}", reply_markup=kb)
        await state.set_state(AdminStates.GroupMenu)
    except ValueError:
        await message.reply("❌ 请输入有效的数字")
    except Exception as e:
        await message.reply(f"❌ 错误: {str(e)}")

@router.callback_query(F.data.startswith("edit_fill_max:"), F.from_user.id.in_(ADMIN_IDS))
async def edit_fill_max(callback: CallbackQuery, state: FSMContext):
    try:
        group_id = int(callback.data.split(":", 1)[1])
        cfg = get_group_config(group_id)
        current = cfg.get("fill_garbage_max_clean_len", 8)
        text = f"输入清理后最大长度（当前: {current}）："
        await callback.message.edit_text(text, reply_markup=None)
        await state.update_data(group_id=group_id)
        await state.set_state(AdminStates.EditFillGarbageMaxClean)
        await callback.answer()
    except Exception as e:
        await callback.answer(f"❌ 错误: {str(e)}", show_alert=True)

@router.message(StateFilter(AdminStates.EditFillGarbageMaxClean), F.from_user.id.in_(ADMIN_IDS))
async def process_fill_max(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        group_id = data.get("group_id")
        cfg = get_group_config(group_id)
        value = int(message.text.strip())
        cfg["fill_garbage_max_clean_len"] = value
        await save_config()
        kb = get_fill_menu_keyboard(group_id)
        await message.reply(f"✅ 清理后最大长度已更新为 {value}", reply_markup=kb)
        await state.set_state(AdminStates.GroupMenu)
    except ValueError:
        await message.reply("❌ 请输入有效的数字")
    except Exception as e:
        await message.reply(f"❌ 错误: {str(e)}")

@router.callback_query(F.data.startswith("edit_fill_ratio:"), F.from_user.id.in_(ADMIN_IDS))
async def edit_fill_ratio(callback: CallbackQuery, state: FSMContext):
    try:
        group_id = int(callback.data.split(":", 1)[1])
        cfg = get_group_config(group_id)
        current = cfg.get("fill_space_ratio", 0.30)
        text = f"输入空格比例阈值（当前: {current:.2f}，范围0-1）："
        await callback.message.edit_text(text, reply_markup=None)
        await state.update_data(group_id=group_id)
        await state.set_state(AdminStates.EditFillSpaceRatio)
        await callback.answer()
    except Exception as e:
        await callback.answer(f"❌ 错误: {str(e)}", show_alert=True)

@router.message(StateFilter(AdminStates.EditFillSpaceRatio), F.from_user.id.in_(ADMIN_IDS))
async def process_fill_ratio(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        group_id = data.get("group_id")
        cfg = get_group_config(group_id)
        value = float(message.text.strip())
        if not (0 <= value <= 1):
            await message.reply("❌ 请输入0-1之间的数值")
            return
        cfg["fill_space_ratio"] = value
        await save_config()
        kb = get_fill_menu_keyboard(group_id)
        await message.reply(f"✅ 空格比例已更新为 {value:.2f}", reply_markup=kb)
        await state.set_state(AdminStates.GroupMenu)
    except ValueError:
        await message.reply("❌ 请输入有效的数字")
    except Exception as e:
        await message.reply(f"❌ 错误: {str(e)}")

# ==================== 自动回复菜单 ====================
@router.callback_query(F.data.startswith("submenu_autoreply:"), F.from_user.id.in_(ADMIN_IDS))
async def autoreply_submenu(callback: CallbackQuery, state: FSMContext):
    try:
        group_id = int(callback.data.split(":", 1)[1])
        cfg = get_group_config(group_id)
        ar = cfg.get("autoreply", {})
        enabled = "✅" if ar.get("enabled") else "❌"
        kw_count = len(ar.get("keywords", []))
        text = f"🤖 自动回复设置\n\n当前状态：{enabled}\n关键词数: {kw_count}"
        kb = get_autoreply_menu_keyboard(group_id)
        await callback.message.edit_text(text, reply_markup=kb)
        await callback.answer()
    except Exception as e:
        await callback.answer(f"❌ 错误: {str(e)}", show_alert=True)

@router.callback_query(F.data.startswith("toggle_ar:"), F.from_user.id.in_(ADMIN_IDS))
async def toggle_autoreply(callback: CallbackQuery):
    try:
        group_id = int(callback.data.split(":", 1)[1])
        cfg = get_group_config(group_id)
        ar = cfg.get("autoreply", {})
        ar["enabled"] = not ar.get("enabled", False)
        await save_config()
        status = "✅ 已启用" if ar["enabled"] else "❌ 已禁用"
        await callback.answer(f"自动回复: {status}", show_alert=True)
        kb = get_autoreply_menu_keyboard(group_id)
        enabled = "✅" if ar.get("enabled") else "❌"
        kw_count = len(ar.get("keywords", []))
        text = f"🤖 自动回复设置\n\n当前状态：{enabled}\n关键词数: {kw_count}"
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception as e:
        await callback.answer(f"❌ 错误: {str(e)}", show_alert=True)

@router.callback_query(F.data.startswith("edit_ar_kw:"), F.from_user.id.in_(ADMIN_IDS))
async def edit_ar_keywords(callback: CallbackQuery, state: FSMContext):
    try:
        group_id = int(callback.data.split(":", 1)[1])
        cfg = get_group_config(group_id)
        ar = cfg.get("autoreply", {})
        keywords = ar.get("keywords", [])
        kw_text = "\n".join(keywords)
        text = f"🔑 编辑自动回复关键词\n\n当前关键词：\n{kw_text if kw_text else '(无)'}\n\n请发送新的关键词（一行一个），或 /clear 清空："
        await callback.message.edit_text(text, reply_markup=None)
        await state.update_data(group_id=group_id)
        await state.set_state(AdminStates.EditAutoreplyKeywords)
        await callback.answer()
    except Exception as e:
        await callback.answer(f"❌ 错误: {str(e)}", show_alert=True)

@router.message(StateFilter(AdminStates.EditAutoreplyKeywords), F.from_user.id.in_(ADMIN_IDS))
async def process_ar_keywords(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        group_id = data.get("group_id")
        cfg = get_group_config(group_id)
        ar = cfg.get("autoreply", {})
        
        if message.text.strip() == "/clear":
            ar["keywords"] = []
        else:
            ar["keywords"] = [x.strip().lower() for x in message.text.strip().split("\n") if x.strip()]
        
        await save_config()
        kb = get_autoreply_menu_keyboard(group_id)
        await message.reply(f"✅ 关键词已更新（共 {len(ar['keywords'])} 个）", reply_markup=kb)
        await state.set_state(AdminStates.GroupMenu)
    except Exception as e:
        await message.reply(f"❌ 错误: {str(e)}")

@router.callback_query(F.data.startswith("edit_ar_text:"), F.from_user.id.in_(ADMIN_IDS))
async def edit_ar_text(callback: CallbackQuery, state: FSMContext):
    try:
        group_id = int(callback.data.split(":", 1)[1])
        cfg = get_group_config(group_id)
        ar = cfg.get("autoreply", {})
        current = ar.get("reply_text", "")
        text = f"📝 编辑自动回复文本\n\n当前内容：\n{current if current else '(无)'}\n\n请发送新的回复文本："
        await callback.message.edit_text(text, reply_markup=None)
        await state.update_data(group_id=group_id)
        await state.set_state(AdminStates.EditAutoreplyText)
        await callback.answer()
    except Exception as e:
        await callback.answer(f"❌ 错误: {str(e)}", show_alert=True)

@router.message(StateFilter(AdminStates.EditAutoreplyText), F.from_user.id.in_(ADMIN_IDS))
async def process_ar_text(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        group_id = data.get("group_id")
        cfg = get_group_config(group_id)
        ar = cfg.get("autoreply", {})
        ar["reply_text"] = message.text.strip()
        
        await save_config()
        kb = get_autoreply_menu_keyboard(group_id)
        await message.reply("✅ 回复文本已更新", reply_markup=kb)
        await state.set_state(AdminStates.GroupMenu)
    except Exception as e:
        await message.reply(f"❌ 错误: {str(e)}")

@router.callback_query(F.data.startswith("edit_ar_btn:"), F.from_user.id.in_(ADMIN_IDS))
async def edit_ar_buttons(callback: CallbackQuery, state: FSMContext):
    try:
        group_id = int(callback.data.split(":", 1)[1])
        cfg = get_group_config(group_id)
        ar = cfg.get("autoreply", {})
        buttons = ar.get("buttons", [])
        btn_text = "\n".join(buttons)
        text = f"🔘 编辑自动回复按钮\n\n当前按钮：\n{btn_text if btn_text else '(无)'}\n\n请发送按钮文本列表（一行一个），或 /clear 清空："
        await callback.message.edit_text(text, reply_markup=None)
        await state.update_data(group_id=group_id)
        await state.set_state(AdminStates.EditAutoreplyButtons)
        await callback.answer()
    except Exception as e:
        await callback.answer(f"❌ 错误: {str(e)}", show_alert=True)

@router.message(StateFilter(AdminStates.EditAutoreplyButtons), F.from_user.id.in_(ADMIN_IDS))
async def process_ar_buttons(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        group_id = data.get("group_id")
        cfg = get_group_config(group_id)
        ar = cfg.get("autoreply", {})
        
        if message.text.strip() == "/clear":
            ar["buttons"] = []
        else:
            ar["buttons"] = [x.strip() for x in message.text.strip().split("\n") if x.strip()]
        
        await save_config()
        kb = get_autoreply_menu_keyboard(group_id)
        await message.reply(f"✅ 按钮已更新（共 {len(ar['buttons'])} 个）", reply_markup=kb)
        await state.set_state(AdminStates.GroupMenu)
    except Exception as e:
        await message.reply(f"❌ 错误: {str(e)}")

@router.callback_query(F.data.startswith("edit_ar_del:"), F.from_user.id.in_(ADMIN_IDS))
async def edit_ar_delete(callback: CallbackQuery, state: FSMContext):
    try:
        group_id = int(callback.data.split(":", 1)[1])
        cfg = get_group_config(group_id)
        ar = cfg.get("autoreply", {})
        user_sec = ar.get("delete_user_sec", 0)
        bot_sec = ar.get("delete_bot_sec", 0)
        text = f"⏱️ 编辑删除延时\n\n当前设置：\n• 用户消息: {user_sec}s（0=不删）\n• 机器人消息: {bot_sec}s（0=不删）\n\n请输入新延时（格式：用户秒 机器人秒，例如 3 5）："
        await callback.message.edit_text(text, reply_markup=None)
        await state.update_data(group_id=group_id)
        await state.set_state(AdminStates.EditAutoreplyDeleteTime)
        await callback.answer()
    except Exception as e:
        await callback.answer(f"❌ 错误: {str(e)}", show_alert=True)

@router.message(StateFilter(AdminStates.EditAutoreplyDeleteTime), F.from_user.id.in_(ADMIN_IDS))
async def process_ar_delete(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        group_id = data.get("group_id")
        cfg = get_group_config(group_id)
        ar = cfg.get("autoreply", {})
        
        parts = message.text.strip().split()
        if len(parts) != 2:
            await message.reply("❌ 格式错误，请输入两个数字（用户秒 机器人秒）")
            return
        
        user_sec = int(parts[0])
        bot_sec = int(parts[1])
        ar["delete_user_sec"] = user_sec
        ar["delete_bot_sec"] = bot_sec
        
        await save_config()
        kb = get_autoreply_menu_keyboard(group_id)
        await message.reply(f"✅ 删除延时已更新（用户 {user_sec}s，机器人 {bot_sec}s）", reply_markup=kb)
        await state.set_state(AdminStates.GroupMenu)
    except ValueError:
        await message.reply("❌ 请输入有效的数字")
    except Exception as e:
        await message.reply(f"❌ 错误: {str(e)}")

# ==================== 群组基础设置 ====================
@router.callback_query(F.data.startswith("submenu_basic:"), F.from_user.id.in_(ADMIN_IDS))
async def basic_submenu(callback: CallbackQuery, state: FSMContext):
    try:
        group_id = int(callback.data.split(":", 1)[1])
        cfg = get_group_config(group_id)
        status = "✅ 已启用" if cfg.get("enabled") else "❌ 已禁用"
        text = f"🎛️ 群组基础设置\n\n群组ID: {group_id}\n状态: {status}"
        kb = get_basic_menu_keyboard(group_id)
        await callback.message.edit_text(text, reply_markup=kb)
        await callback.answer()
    except Exception as e:
        await callback.answer(f"❌ 错误: {str(e)}", show_alert=True)

@router.callback_query(F.data.startswith("toggle_group:"), F.from_user.id.in_(ADMIN_IDS))
async def toggle_group(callback: CallbackQuery):
    try:
        group_id = int(callback.data.split(":", 1)[1])
        cfg = get_group_config(group_id)
        cfg["enabled"] = not cfg.get("enabled", True)
        await save_config()
        status = "✅ 已启用" if cfg["enabled"] else "❌ 已禁用"
        await callback.answer(f"群组状态: {status}", show_alert=True)
        kb = get_basic_menu_keyboard(group_id)
        status_display = "✅ 已启用" if cfg.get("enabled") else "❌ 已禁用"
        text = f"🎛️ 群组基础设置\n\n群组ID: {group_id}\n状态: {status_display}"
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception as e:
        await callback.answer(f"❌ 错误: {str(e)}", show_alert=True)

# ==================== 状态查看 ====================
@router.callback_query(F.data == "view_status", F.from_user.id.in_(ADMIN_IDS))
async def view_status(callback: CallbackQuery):
    try:
        group_count = len(GROUP_IDS)
        admin_count = len(ADMIN_IDS)
        async with lock:
            report_count = len(reports)
        
        text = f"📊 机器人状态\n\n"
        text += f"✅ 运行正常\n"
        text += f"👮 管理员数: {admin_count}\n"
        text += f"📋 监控群组: {group_count}\n"
        text += f"📁 举报记录: {report_count}\n"
        
        await callback.answer(text, show_alert=True)
    except Exception as e:
        await callback.answer(f"❌ 错误: {str(e)}", show_alert=True)

# ==================== 群内检测逻辑（原有保持不变） ====================
FILL_CHARS = set(r" .,，。！？*\\\~`-_=+[]{}()\"'\\|\n\t\r　")

user_short_msg_history = {}
exempt_users = {}

async def load_data():
    global reports
    try:
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                for k, v in data.items():
                    v["reporters"] = set(v.get("reporters", []))
                    reports[int(k)] = v
    except Exception as e:
        print("数据加载失败（首次正常）:", e)

async def save_data():
    async with lock:
        try:
            data_to_save = {str(k): {**v, "reporters": list(v["reporters"])} for k, v in reports.items()}
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data_to_save, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("保存失败:", e)

def get_profile_hash(bio: str, full_name: str, username: str | None) -> str:
    profile_str = f"{bio}|{full_name}|{username or ''}"
    return hashlib.sha256(profile_str.encode('utf-8')).hexdigest()

@router.message(F.chat.id.in_(GROUP_IDS))
async def check_user_info(message: Message):
    if not message.from_user or message.from_user.is_bot:
        return
    
    # 检查群组是否启用
    cfg = get_group_config(message.chat.id)
    if not cfg.get("enabled", True):
        return
    
    user = message.from_user
    user_id = user.id
    
    async with lock:
        if user_id in exempt_users:
            try:
                chat_info = await bot.get_chat(user_id)
                current_hash = get_profile_hash(
                    (chat_info.bio or ""),
                    user.full_name or "",
                    user.username or ""
                )
                if current_hash == exempt_users[user_id]:
                    return
                else:
                    exempt_users.pop(user_id, None)
            except Exception:
                pass
    
    try:
        chat_info = await bot.get_chat(user_id)
        bio = (chat_info.bio or "").lower()
        
        has_link_in_bio = cfg.get("check_bio_link", True) and any(x in bio for x in ["http://", "https://", "t.me/", "@"])
        has_spam_in_bio = cfg.get("check_bio_keywords", True) and any(kw.lower() in bio for kw in cfg.get("bio_keywords", []))
        bio_trigger = has_link_in_bio or has_spam_in_bio
        
        display_name = (user.full_name or "").lower()
        has_spam_in_display = cfg.get("check_display_keywords", True) and any(kw.lower() in display_name for kw in cfg.get("display_keywords", []))
        
        if bio_trigger or has_spam_in_display:
            reason_parts = []
            if has_link_in_bio: 
                reason_parts.append("简介含链接")
            if has_spam_in_bio: 
                reason_parts.append("简介含敏感词")
            if has_spam_in_display: 
                reason_parts.append("显示名称含敏感词")
            
            reason_text = " + ".join(reason_parts)
            warning_text = (
                f"⚠️ 检测到疑似广告引流规避（{reason_text}）\n"
                f"用户ID: {user.id}\n"
                f"显示名称: {user.full_name}\n"
                f"举报数: 0"
            )
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="举报该用户", callback_data=f"report:{message.message_id}"),
                InlineKeyboardButton(text="误判/豁免 👮‍♂️", callback_data=f"exempt:{message.message_id}")
            ]])
            warning = await message.reply(warning_text, reply_markup=keyboard)
            
            async with lock:
                reports[message.message_id] = {
                    "warning_id": warning.message_id,
                    "suspect_id": user.id,
                    "chat_id": message.chat.id,
                    "reporters": set(),
                    "original_text": warning_text,
                    "original_message_id": message.message_id
                }
            await save_data()
    except Exception as e:
        print("用户信息检测异常:", e)

@router.message(F.chat.id.in_(GROUP_IDS), F.text)
async def detect_short_or_filled_spam(message: Message):
    if not message.from_user or message.from_user.is_bot:
        return
    
    # 检查群组是否启用
    cfg = get_group_config(message.chat.id)
    if not cfg.get("enabled", True):
        return
    
    user_id = message.from_user.id
    
    async with lock:
        if user_id in exempt_users:
            try:
                chat_info = await bot.get_chat(user_id)
                bio = (chat_info.bio or "")
                full_name = message.from_user.full_name or ""
                username = message.from_user.username
                current_hash = get_profile_hash(bio, full_name, username)
                if current_hash == exempt_users[user_id]:
                    return
                else:
                    exempt_users.pop(user_id, None)
            except Exception:
                pass
    
    text = message.text
    text_len = len(text)
    now = time.time()
    
    reason = None
    
    # 填充垃圾检测
    if cfg.get("fill_garbage_detection", True):
        min_raw = cfg.get("fill_garbage_min_raw_len", 12)
        max_clean = cfg.get("fill_garbage_max_clean_len", 8)
        space_ratio_threshold = cfg.get("fill_space_ratio", 0.30)
        
        if text_len >= min_raw:
            cleaned = ''.join(c for c in text if c not in FILL_CHARS).strip()
            clean_len = len(cleaned)
            space_ratio = (text.count(" ") + text.count("　")) / text_len if text_len > 0 else 0
            if (clean_len <= max_clean) or (space_ratio >= space_ratio_threshold and clean_len <= 12):
                reason = "单次填充式规避"
    
    # 短消息检测
    if not reason and cfg.get("short_msg_detection", True):
        threshold = cfg.get("short_msg_threshold", 3)
        min_count = cfg.get("min_consecutive_count", 2)
        time_window = cfg.get("time_window_seconds", 60)
        
        if user_id not in user_short_msg_history:
            user_short_msg_history[user_id] = deque(maxlen=15)
        
        history = user_short_msg_history[user_id]
        while history and now - history[0][0] > time_window:
            history.popleft()
        history.append((now, text))
        
        recent = list(history)[-min_count:]
        if len(recent) >= min_count and all(len(t.strip()) <= threshold for _, t in recent):
            reason = "连续极短消息"
    
    if reason:
        await send_warning(message, user_id, reason)

async def send_warning(message: Message, user_id: int, reason: str):
    try:
        warning_text = f"⚠️ 检测到疑似广告引流规避（{reason}）\n用户ID: {user_id}\n举报数: 0"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="举报该用户", callback_data=f"report:{message.message_id}"),
            InlineKeyboardButton(text="误判/豁免 👮‍♂️", callback_data=f"exempt:{message.message_id}")
        ]])
        warning = await message.reply(warning_text, reply_markup=keyboard)
        
        async with lock:
            reports[message.message_id] = {
                "warning_id": warning.message_id,
                "suspect_id": user_id,
                "chat_id": message.chat.id,
                "reporters": set(),
                "original_text": warning_text,
                "original_message_id": message.message_id
            }
        await save_data()
    except Exception as e:
        print("发送警告失败:", e)

@router.callback_query(F.data.startswith("report:"))
async def handle_report(callback: CallbackQuery):
    try:
        original_id = int(callback.data.split(":", 1)[1])
        reporter_id = callback.from_user.id
        
        async with lock:
            if original_id not in reports:
                await callback.answer("该举报已过期", show_alert=True)
                return
            data = reports[original_id]
            if reporter_id in data["reporters"]:
                await callback.answer("您已经举报过了", show_alert=True)
                return
            data["reporters"].add(reporter_id)
            count = len(data["reporters"])
            suspect_id = data["suspect_id"]
            warning_id = data["warning_id"]
            chat_id = data["chat_id"]
            original_text = data.get("original_text", "⚠️ 检测到疑似广告引流规避\n用户ID: 未知")
        
        lines = original_text.splitlines()
        prefix = "\n".join(lines[:2]) if len(lines) >= 2 else original_text
        
        if count >= 3:
            status = f"🚨 超3人举报 已通知管理员\n\n举报人数: {count}"
            await bot.send_message(list(ADMIN_IDS)[0], f"多人举报\n用户ID: {suspect_id}\n群组: {chat_id}")
        else:
            status = f"🚨 已有人举报\n\n举报人数: {count}"
        
        new_text = f"{prefix}\n{status}"
        
        keyboard_list = callback.message.reply_markup.inline_keyboard[:] if callback.message.reply_markup else []
        if not any("ban" in str(btn.callback_data) for row in keyboard_list for btn in row):
            keyboard_list.append([
                InlineKeyboardButton(text="封禁24小时（👮‍♀️）", callback_data=f"ban24h:{original_id}"),
                InlineKeyboardButton(text="永久封禁（👮‍♂️）", callback_data=f"banperm:{original_id}")
            ])
        new_keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_list)
        
        await bot.edit_message_text(chat_id=chat_id, message_id=warning_id, text=new_text, reply_markup=new_keyboard)
        await save_data()
        await callback.answer(f"举报成功！当前 {count} 人")
    except Exception as e:
        print("举报处理异常:", e)
        await callback.answer("操作失败", show_alert=True)

@router.callback_query(F.data.startswith(("ban24h:", "banperm:")))
async def handle_ban(callback: CallbackQuery):
    try:
        action, original_id_str = callback.data.split(":", 1)
        original_id = int(original_id_str)
        caller_id = callback.from_user.id
        chat_id = callback.message.chat.id
        
        if caller_id not in ADMIN_IDS:
            await callback.answer("仅管理员可操作", show_alert=True)
            return
        
        async with lock:
            if original_id not in reports:
                await callback.answer("记录已过期", show_alert=True)
                return
            data = reports[original_id]
            suspect_id = data["suspect_id"]
            warning_id = data["warning_id"]
            original_message_id = data.get("original_message_id")
            original_text = data.get("original_text", "⚠️ 检测到疑似广告引流规避\n用户ID: 未知")
        
        until_date = int(time.time()) + 86400 if action == "ban24h" else None
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=suspect_id,
            permissions=ChatPermissions(
                can_send_messages=False,
                can_send_media_messages=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
                can_change_info=False,
                can_invite_users=False,
                can_pin_messages=False
            ),
            until_date=until_date
        )
        
        ban_type = "禁言24小时" if action == "ban24h" else "永久限制"
        lines = original_text.splitlines()
        prefix = "\n".join(lines[:2]) if len(lines) >= 2 else original_text
        new_text = f"{prefix}\n🚨 已由管理员{ban_type}\n举报人数: {len(data['reporters'])}"
        
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=warning_id,
            text=new_text,
            reply_markup=None
        )
        
        await callback.answer(f"已{ban_type}", show_alert=True)
        print(f"管理员 {caller_id} 对 {suspect_id} 执行 {ban_type} 在群 {chat_id}")
        
        async def delayed_delete():
            await asyncio.sleep(10)
            try:
                await bot.delete_message(chat_id, warning_id)
                print(f"删除警告消息 {warning_id}")
            except TelegramBadRequest as e:
                print(f"删除警告失败 {warning_id}: {e}")
            try:
                if original_message_id:
                    await bot.delete_message(chat_id, original_message_id)
                    print(f"删除用户原消息 {original_message_id}")
            except TelegramBadRequest as e:
                print(f"删除用户消息失败 {original_message_id}: {e}")
        
        asyncio.create_task(delayed_delete())
        
        async with lock:
            reports.pop(original_id, None)
        await save_data()
    
    except TelegramBadRequest as e:
        if "user_not_participant" in str(e).lower():
            await callback.answer("用户不在群组", show_alert=True)
        elif "not enough rights" in str(e).lower():
            await callback.answer("机器人缺少权限", show_alert=True)
        else:
            await callback.answer(f"操作失败: {str(e)}", show_alert=True)
    except Exception as e:
        print("封禁异常:", e)
        await callback.answer("操作失败", show_alert=True)

@router.callback_query(F.data.startswith("exempt:"))
async def handle_exempt(callback: CallbackQuery):
    try:
        original_id = int(callback.data.split(":", 1)[1])
        caller_id = callback.from_user.id
        chat_id = callback.message.chat.id
        
        if caller_id not in ADMIN_IDS:
            await callback.answer("仅管理员可操作", show_alert=True)
            return
        
        async with lock:
            if original_id not in reports:
                await callback.answer("记录已过期", show_alert=True)
                return
            data = reports[original_id]
            suspect_id = data["suspect_id"]
            warning_id = data["warning_id"]
        
        suspect_user = await bot.get_chat(suspect_id)
        bio = (suspect_user.bio or "")
        full_name = f"{suspect_user.first_name or ''} {suspect_user.last_name or ''}".strip()
        username = suspect_user.username
        profile_hash = get_profile_hash(bio, full_name, username)
        
        async with lock:
            exempt_users[suspect_id] = profile_hash
            await bot.delete_message(chat_id, warning_id)
        
        await callback.answer("已豁免此人 👮‍♂️\n后续资料不变将不再检测", show_alert=True)
        
        async with lock:
            reports.pop(original_id, None)
        await save_data()
    
    except TelegramBadRequest as e:
        await callback.answer(f"操作失败: {str(e)}", show_alert=True)
    except Exception as e:
        print("豁免异常:", e)
        await callback.answer("操作失败", show_alert=True)

async def cleanup_deleted_messages():
    """定期清理已删除的消息记录"""
    while True:
        await asyncio.sleep(300)
        to_remove = []
        async with lock:
            check_list = list(reports.items())
        for orig_id, data in check_list:
            try:
                test_msg = await bot.forward_message(
                    chat_id=list(ADMIN_IDS)[0],
                    from_chat_id=data["chat_id"],
                    message_id=orig_id
                )
                await bot.delete_message(list(ADMIN_IDS)[0], test_msg.message_id)
            except TelegramBadRequest as e:
                if "not found" in str(e).lower() or "message to forward not found" in str(e).lower():
                    try:
                        await bot.delete_message(data["chat_id"], data["warning_id"])
                        to_remove.append(orig_id)
                        print(f"同步删除警告: 原消息 {orig_id} 已删")
                    except Exception:
                        pass
        if to_remove:
            async with lock:
                for oid in to_remove:
                    reports.pop(oid, None)
            await save_data()
        await asyncio.sleep(1)

async def main():
    print("🚀 机器人启动成功")
    await load_config()
    await load_data()
    asyncio.create_task(cleanup_deleted_messages())
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
