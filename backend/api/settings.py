from fastapi import APIRouter, Request

from database import get_all_settings, set_setting
from models.schemas import SettingUpdateIn, SettingsOut

router = APIRouter(prefix="/settings")


@router.get("", response_model=SettingsOut)
async def get_settings(request: Request):
    db = request.app.state.db
    all_s = await get_all_settings(db)
    return SettingsOut(settings=all_s)


@router.put("")
async def update_setting(request: Request, body: SettingUpdateIn):
    db = request.app.state.db
    await set_setting(db, body.key, body.value)
    return {"ok": True, "key": body.key, "value": body.value}
