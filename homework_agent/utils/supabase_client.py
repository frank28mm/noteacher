"""Supabase Storage 客户端工具
用于处理文件上传到 Supabase Storage 并获取公开访问 URL。
支持图片上传（含 HEIC/HEIF 转 JPEG），支持 PDF 拆页为 JPEG（最多 8 页）。
"""
import mimetypes
import os
import uuid
import tempfile
from pathlib import Path

from supabase import create_client, Client
from typing import Optional, Tuple, List

from PIL import Image

try:
    import fitz  # PyMuPDF
    FITZ_AVAILABLE = True
except Exception:
    FITZ_AVAILABLE = False

# 尝试注册 HEIF 解码器，便于 HEIC/HEIF 转码为 JPEG
try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:
    pillow_heif = None


class SupabaseStorageClient:
    """Supabase Storage 客户端"""

    def __init__(self):
        """初始化 Supabase 客户端"""
        self.url = os.getenv("SUPABASE_URL")
        self.key = os.getenv("SUPABASE_KEY")
        self.bucket = os.getenv("SUPABASE_BUCKET", "homework-images")

        if not self.url or not self.key:
            raise ValueError("SUPABASE_URL 和 SUPABASE_KEY 环境变量必须设置")

        self.client: Client = create_client(self.url, self.key)

    def _prepare_image_for_upload(self, file_path: str) -> Tuple[str, str, Optional[str], Optional[Tuple[int, int]]]:
        """
        确认并标准化图片文件：
        - 仅接受 image/*
        - 若为 HEIC/HEIF/AVIF，则转为 JPEG 临时文件
        Returns: (path_to_upload, mime_type, temp_path_for_cleanup, (w,h))
        """
        mime_guess, _ = mimetypes.guess_type(file_path)
        temp_path: Optional[str] = None
        size: Optional[Tuple[int, int]] = None

        try:
            with Image.open(file_path) as img:
                size = img.size
                fmt = (img.format or "").upper()
                if fmt in {"HEIC", "HEIF", "AVIF"}:
                    if pillow_heif is None:
                        raise ValueError("检测到 HEIC/HEIF 图片，当前环境缺少 pillow-heif 依赖")
                    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
                    img.convert("RGB").save(tmp.name, format="JPEG", quality=95)
                    temp_path = tmp.name
                    return temp_path, "image/jpeg", temp_path, size

                mime = mime_guess or Image.MIME.get(img.format) or "image/jpeg"
                if not mime.startswith("image/"):
                    raise ValueError(f"不支持的文件类型: {mime}")
                return file_path, mime, temp_path, size
        except ValueError:
            raise
        except Exception:
            if mime_guess and mime_guess.startswith("image/"):
                return file_path, mime_guess, temp_path, size
            raise ValueError("无法识别图片文件，请使用 JPG/PNG 上传")

    def _convert_pdf_to_images(self, file_path: str, max_pages: int = 8) -> List[Tuple[str, Tuple[int, int]]]:
        """将 PDF 前 max_pages 页转为 JPEG 临时文件，返回 (path,(w,h)) 列表"""
        if not FITZ_AVAILABLE:
            raise ValueError("当前环境缺少 PyMuPDF（fitz），无法处理 PDF，请先安装依赖或上传图片格式")
        temp_paths: List[Tuple[str, Tuple[int, int]]] = []
        try:
            doc = fitz.open(file_path)
        except Exception as e:
            raise ValueError(f"无法读取 PDF：{e}")

        pages = min(len(doc), max_pages)
        if pages == 0:
            raise ValueError("PDF 无有效页面")

        for i in range(pages):
            page = doc.load_page(i)
            pix = page.get_pixmap(dpi=200)
            tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            pix.save(tmp.name, output='jpeg')
            temp_paths.append((tmp.name, (pix.width, pix.height)))
        doc.close()
        return temp_paths

    def upload_files(self, file_path: str, prefix: str = "demo/", min_side: int = 0) -> List[str]:
        """上传文件到 Supabase Storage 并返回公开访问 URL 列表

        - 图片：1 张 -> 1 个 URL
        - PDF：拆页（最多 8 页）-> 多个 URL

        Args:
            file_path: 本地文件路径
            prefix: 存储路径前缀 (默认: "demo/")

        Returns:
            公开访问的 URL 列表

        Raises:
            ValueError: 文件不存在或类型不支持
            Exception: 上传失败
        """
        # 验证文件存在
        if not os.path.exists(file_path):
            raise ValueError(f"文件不存在: {file_path}")

        # 验证文件大小 (<20MB)
        file_size = os.path.getsize(file_path)
        if file_size > 20 * 1024 * 1024:
            raise ValueError(f"文件超过 20MB: {file_size / 1024 / 1024:.2f}MB")

        ext = Path(file_path).suffix.lower()
        mime_guess, _ = mimetypes.guess_type(file_path)

        upload_targets: List[Tuple[str, str, Optional[str]]] = []
        temp_paths: List[str] = []

        if ext == ".pdf" or (mime_guess and mime_guess == "application/pdf"):
            pdf_images = self._convert_pdf_to_images(file_path, max_pages=8)
            for img_path, size in pdf_images:
                temp_paths.append(img_path)
                up_path, mime_type, tmp, detected_size = self._prepare_image_for_upload(img_path)
                final_size = detected_size or size
                upload_targets.append((up_path, mime_type, tmp, final_size))
                if tmp and tmp not in temp_paths:
                    temp_paths.append(tmp)
        else:
            up_path, mime_type, tmp, size = self._prepare_image_for_upload(file_path)
            upload_targets.append((up_path, mime_type, tmp, size))
            if tmp:
                temp_paths.append(tmp)

        if min_side > 0:
            for _, _, _, size in upload_targets:
                if size:
                    w, h = size
                    if w < min_side or h < min_side:
                        raise ValueError(f"图片尺寸过小：{w}x{h}，最小边需 >= {min_side}px")

        urls: List[str] = []
        try:
            for up_path, mime_type, _, _ in upload_targets:
                file_ext = Path(up_path).suffix or ".jpg"
                unique_filename = f"{prefix}{uuid.uuid4().hex}{file_ext}"
                with open(up_path, "rb") as f:
                    file_content = f.read()
                self.client.storage.from_(self.bucket).upload(
                    path=unique_filename,
                    file=file_content,
                    file_options={"content-type": mime_type}
                )
                public_url = self.client.storage.from_(self.bucket).get_public_url(unique_filename)
                # Supabase Python SDK 2.x 会返回末尾带 "?" 的直链，这里清理掉避免下游 URL 校验/超时问题
                public_url = public_url.rstrip("?")
                urls.append(public_url)
            return urls
        except Exception as e:
            raise Exception(f"上传到 Supabase 失败: {str(e)}")
        finally:
            for p in temp_paths:
                if p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass

    def upload_image(self, file_path: str, prefix: str = "demo/", min_side: int = 0) -> str:
        """兼容旧接口，返回首个 URL"""
        urls = self.upload_files(file_path, prefix=prefix, min_side=min_side)
        if not urls:
            raise Exception("上传结果为空")
        return urls[0]

    def upload_bytes(
        self,
        file_content: bytes,
        *,
        mime_type: str = "image/jpeg",
        suffix: str = ".jpg",
        prefix: str = "slices/",
    ) -> str:
        """上传内存中的二进制内容（用于切片/裁剪图）并返回公网 URL"""
        file_ext = suffix if suffix.startswith(".") else f".{suffix}"
        unique_filename = f"{prefix}{uuid.uuid4().hex}{file_ext}"
        self.client.storage.from_(self.bucket).upload(
            path=unique_filename,
            file=file_content,
            file_options={"content-type": mime_type},
        )
        public_url = self.client.storage.from_(self.bucket).get_public_url(unique_filename)
        return str(public_url).rstrip("?")


def get_storage_client() -> SupabaseStorageClient:
    """获取 SupabaseStorageClient 实例 (单例模式)"""
    return SupabaseStorageClient()
