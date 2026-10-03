"""把本地图片上传到应用自有 HTTP 接口的发布器示例。

上传端点应接受 multipart 字段 ``file``，成功后返回 JSON ``{"public_url": "https://..."}``。
只有显式调用 publish_local_markdown_image 才会发起请求。
"""

import os

import aiohttp

from nonebot.adapters.wind.media import ImagePublisher, resolve_image_url


class ApplicationImagePublisher:
    """使用配置好的应用上传 API 发布图片。"""

    async def publish_image(self, image_data: bytes, file_name: str) -> str:
        endpoint = os.environ["IMAGE_UPLOAD_URL"]
        token = os.environ.get("IMAGE_UPLOAD_TOKEN")
        form = aiohttp.FormData()
        form.add_field("file", image_data, filename=file_name, content_type="application/octet-stream")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(endpoint, data=form, headers=headers) as response:
                response.raise_for_status()
                payload = await response.json()
        public_url = payload.get("public_url")
        if not isinstance(public_url, str):
            raise ValueError("upload endpoint response must contain a public_url string")
        return public_url


async def publish_local_markdown_image(path: str) -> str:
    publisher: ImagePublisher = ApplicationImagePublisher()
    return await resolve_image_url(path, publisher)


# 定义函数和导入本模块均不会上传文件。设置 IMAGE_UPLOAD_URL（及可选
# IMAGE_UPLOAD_TOKEN）后，调用 publish_local_markdown_image 才会执行 HTTP 上传。
