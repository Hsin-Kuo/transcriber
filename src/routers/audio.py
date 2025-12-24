"""音檔處理路由"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from typing import List, Dict, Any
from pathlib import Path
import json
import tempfile

from ..auth.dependencies import get_current_user
from ..services.audio_service import AudioService


router = APIRouter(prefix="/audio", tags=["Audio"])


# 全域 AudioService 實例（用於管理片段）
_audio_service = None


def get_audio_service() -> AudioService:
    """依賴注入：獲取 AudioService 實例

    Returns:
        AudioService 實例
    """
    global _audio_service
    if _audio_service is None:
        # 使用 output 目錄作為片段儲存位置
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        _audio_service = AudioService(output_dir=output_dir)
    return _audio_service


@router.post("/clip")
async def clip_audio(
    audio_file: UploadFile = File(...),
    regions: str = Form(..., description="區段 JSON 陣列，格式：[{start, end, id}]"),
    audio_service: AudioService = Depends(get_audio_service),
    current_user: dict = Depends(get_current_user)
) -> Dict[str, List[Dict[str, Any]]]:
    """剪輯音訊文件中的指定區段

    Args:
        audio_file: 原始音訊文件
        regions: JSON 字串，包含區段陣列 [{"start": 10.5, "end": 25.3, "id": "xxx"}]
        audio_service: AudioService 實例
        current_user: 當前用戶

    Returns:
        {
            "clips": [
                {"clip_id": "...", "filename": "...", "duration": 14.8},
                ...
            ]
        }
    """
    temp_dir = Path(tempfile.mkdtemp())

    try:
        # 保存上傳的音檔
        file_suffix = Path(audio_file.filename).suffix
        temp_audio_path = temp_dir / f"input{file_suffix}"

        with temp_audio_path.open("wb") as f:
            content = await audio_file.read()
            f.write(content)

        print(f"🎵 載入音檔進行剪輯：{audio_file.filename}")

        # 解析區段資料
        try:
            regions_data = json.loads(regions)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="區段資料格式錯誤")

        if not isinstance(regions_data, list):
            raise HTTPException(status_code=400, detail="區段資料必須是陣列")

        # 使用 AudioService 進行剪輯
        clips = audio_service.clip_audio_regions(temp_audio_path, regions_data)

        print(f"✅ 成功剪輯 {len(clips)} 個片段")

        return {"clips": clips}

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ 音檔剪輯失敗：{e}")
        raise HTTPException(status_code=500, detail=f"音檔剪輯失敗：{str(e)}")

    finally:
        # 清理臨時目錄
        import shutil
        if temp_dir.exists():
            shutil.rmtree(temp_dir)


@router.post("/merge")
async def merge_audio(
    clip_ids: str = Form(..., description="要合併的片段 ID 陣列（JSON 字串）"),
    mode: str = Form("different-files", description="合併模式"),
    audio_service: AudioService = Depends(get_audio_service),
    current_user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """合併多個音訊片段

    Args:
        clip_ids: 片段 ID 陣列（JSON 字串）
        mode: 合併模式
            - "different-files": 合併不同音檔（中間無間隔）
            - "same-file-clips": 合併同一音檔的片段（保持原始時間順序）
        audio_service: AudioService 實例
        current_user: 當前用戶

    Returns:
        {
            "merged_id": "...",
            "filename": "...",
            "duration": 120.5
        }
    """
    try:
        # 解析 clip_ids
        clip_ids_list = json.loads(clip_ids)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="片段 ID 格式錯誤")

    if not isinstance(clip_ids_list, list):
        raise HTTPException(status_code=400, detail="片段 ID 必須是陣列")

    if len(clip_ids_list) < 2:
        raise HTTPException(status_code=400, detail="至少需要 2 個片段")

    try:
        # 使用 AudioService 合併片段
        result = audio_service.merge_clips(clip_ids_list, mode)

        print(f"✅ 成功合併 {len(clip_ids_list)} 個片段")

        return result

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        print(f"❌ 音檔合併失敗：{e}")
        raise HTTPException(status_code=500, detail=f"音檔合併失敗：{str(e)}")


@router.get("/download/{clip_id}")
async def download_clip(
    clip_id: str,
    audio_service: AudioService = Depends(get_audio_service),
    current_user: dict = Depends(get_current_user)
):
    """下載音訊片段或合併結果

    Args:
        clip_id: 片段 ID
        audio_service: AudioService 實例
        current_user: 當前用戶

    Returns:
        FileResponse 音檔文件
    """
    # 獲取片段資訊
    clip_data = audio_service.get_clip(clip_id)

    if clip_data is None:
        raise HTTPException(status_code=404, detail="片段不存在")

    filepath = Path(clip_data["path"])

    if not filepath.exists():
        raise HTTPException(status_code=404, detail="檔案已被刪除")

    return FileResponse(
        path=str(filepath),
        filename=clip_data["filename"],
        media_type="audio/mpeg"
    )


@router.post("/cleanup")
async def cleanup_old_clips(
    max_age_hours: int = 24,
    audio_service: AudioService = Depends(get_audio_service),
    current_user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """清理超過指定時間的音訊片段

    Args:
        max_age_hours: 最大保留時間（小時），預設 24 小時
        audio_service: AudioService 實例
        current_user: 當前用戶

    Returns:
        {"deleted_count": 5, "message": "已清理 5 個過期片段"}
    """
    try:
        deleted_count = audio_service.cleanup_old_clips(max_age_hours)

        return {
            "deleted_count": deleted_count,
            "message": f"已清理 {deleted_count} 個過期片段"
        }

    except Exception as e:
        print(f"❌ 清理片段失敗：{e}")
        raise HTTPException(status_code=500, detail=f"清理失敗：{str(e)}")


@router.post("/convert-to-web-format")
async def convert_audio_to_web_format(
    audio_file: UploadFile = File(..., description="要轉換的音檔"),
    audio_service: AudioService = Depends(get_audio_service),
    current_user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """將音訊檔案轉換為瀏覽器相容的格式 (MP3)

    Args:
        audio_file: 要轉換的音檔
        audio_service: AudioService 實例
        current_user: 當前用戶

    Returns:
        {
            "clip_id": "...",
            "filename": "...",
            "size_mb": 2.5
        }
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)

        # 儲存上傳的檔案
        temp_input_path = temp_dir_path / audio_file.filename
        with open(temp_input_path, "wb") as f:
            content = await audio_file.read()
            f.write(content)

        try:
            print(f"🔄 正在轉換音訊格式：{audio_file.filename}")

            # 使用 AudioService 轉換格式
            result = audio_service.convert_to_web_format(temp_input_path)

            print(f"✅ 轉換完成：{result['filename']} ({result['size_mb']} MB)")

            return result

        except Exception as e:
            print(f"❌ 音訊轉換失敗：{e}")
            raise HTTPException(status_code=500, detail=f"轉換失敗：{str(e)}")
