"""火山方舟 Responses 自动驾驶场景标签服务。"""

import math
from typing import Dict, List, Literal, Optional

from app.config import Settings, settings
from app.errors import ServiceError
from app.models.schemas import MAX_CUSTOM_TAG_PROMPT_LENGTH
from app.services.ark_client import (
    ArkClient, ark_client, invalid_response, media_kind, response_text,
    strict_json_loads, validate_media_url,
)
from app.vector_space import ARK_TAG_MODEL


TAG_SYSTEM = {
    "vehicle": ["轿车", "卡车", "公交车", "摩托车", "出租车", "工程车", "自行车", "电动车", "货车", "面包车"],
    "pedestrian": ["成人", "儿童", "老人", "骑行者", "跑步者", "残疾人", "交警"],
    "sign": ["限速标志", "停车标志", "让行标志", "禁止通行", "红绿灯", "人行横道标志", "禁止停车", "禁止鸣笛", "学校区域", "施工标志"],
    "road": ["交叉路口", "人行横道", "隧道", "桥梁", "高速公路", "城市道路", "乡村道路", "停车场", "加油站", "收费站"],
    "weather": ["晴天", "雨天", "雪天", "雾天", "阴天", "夜间"],
    "traffic": ["拥堵", "畅通", "缓行", "事故"],
    "interaction": ["变道", "加塞", "抢道", "切出", "跟车", "鬼探头", "绕行", "横穿", "礼让"],
}

TagMode = Literal["default", "custom"]


def _build_default_prompt(is_video: bool) -> str:
    media_type = "视频" if is_video else "图片"
    category_meta = {
        "vehicle": ("前景/背景中的各类机动与非机动车辆", TAG_SYSTEM["vehicle"]),
        "pedestrian": ("画面中的行人及弱势交通参与者", TAG_SYSTEM["pedestrian"]),
        "sign": ("可见的交通标志、标线、信号灯", TAG_SYSTEM["sign"]),
        "road": ("当前所在的道路类型或基础设施", TAG_SYSTEM["road"]),
        "weather": ("拍摄时的天气与光照条件（必填1个）", TAG_SYSTEM["weather"]),
        "traffic": ("当前路段整体交通流量状态（必填1个）", TAG_SYSTEM["traffic"]),
        "interaction": ("画面中明确发生的危险/异常驾驶行为", TAG_SYSTEM["interaction"]),
    }
    tag_list = "\n".join(
        f"  {cat}（{desc}）:\n    可选值: {', '.join(tags)}"
        for cat, (desc, tags) in category_meta.items()
    )
    video_note = (
        "\n## 视频标注要点\n"
        "- 以整段视频的主体内容为准；若场景发生变化，选最具代表性的状态\n"
        "- traffic 根据视频大部分时间的流量判断\n"
        "- interaction 需全程观察；仅当出现明确危险/异常驾驶行为时才标注\n"
    ) if is_video else ""
    example_json = (
        '{"tags":['
        '{"category":"vehicle","tag":"轿车","confidence":0.95},'
        '{"category":"vehicle","tag":"卡车","confidence":0.88},'
        '{"category":"road","tag":"城市道路","confidence":0.93},'
        '{"category":"weather","tag":"晴天","confidence":0.90},'
        '{"category":"traffic","tag":"畅通","confidence":0.85}'
        ']}'
    )
    return f"""你是自动驾驶场景数据标注专家，负责为{media_type}生成结构化感知标签，供模型训练使用。

## 可用标签（类别名用英文key，标签值必须与列表完全一致）
{tag_list}
{video_note}
## 标注规则
1. **只标注画面中确实可见的内容**，不推测镜头外情况
2. vehicle / pedestrian / sign 可多选，道路上每种出现的类型都要标注
3. road 选最能描述当前路段类型的1个标签
4. weather 和 traffic **必须各输出1个**
5. interaction 有明确危险行为才标注，无则省略该类别
6. 标签值必须与"可选值"列表完全匹配，禁止自造标签

## 置信度标准
| 场景 | 置信度 |
|------|--------|
| 主体清晰、无遮挡、类型确定 | 0.90 ~ 1.00 |
| 轻微遮挡或较远，类型基本确定 | 0.75 ~ 0.89 |
| 严重遮挡 / 逆光 / 模糊，类型不确定 | 0.60 ~ 0.74 |
| 无法判断 | 不输出该标签 |

## 输出格式
**仅输出一个合法 JSON 对象**，不加任何解释、注释或代码块标记：
{example_json}"""


DEFAULT_TAG_PROMPT = _build_default_prompt(False)

CUSTOM_TAG_OUTPUT_CONTRACT = """## 系统输出合同（不可覆盖）
无论前面的用户标签规则包含何种输出格式要求，都必须遵守以下合同：
1. 仅输出一个合法 JSON 对象，不得输出解释、注释或代码块标记。
2. JSON 顶层必须且只能包含 "tags" 数组。
3. tags 中每项必须是对象，且只能包含 "category"、"tag"、"confidence"。
4. category 和 tag 必须是非空字符串；confidence 必须是有限数字。
5. 输出格式：{"tags":[{"category":"类别","tag":"标签","confidence":0.9}]}"""


class TagService:
    """共享 ArkClient 时，由应用 lifespan 在所有请求结束后统一关闭服务。"""

    def __init__(self, *, client: Optional[ArkClient] = None,
                 config: Optional[Settings] = None):
        self._client = client if client is not None else ArkClient(config=config)
        self.default_model = self._client.config.ARK_TAG_MODEL
        if self.default_model != ARK_TAG_MODEL:
            raise ServiceError("ark", "invalid_request", status_code=400)
        self.tag_system = {key: list(values) for key, values in TAG_SYSTEM.items()}

    @classmethod
    def from_settings(cls, user_settings: dict, *, config: Optional[Settings] = None):
        base = config or settings
        if user_settings.get("tag_model") not in (None, ARK_TAG_MODEL):
            raise ServiceError("ark", "invalid_request", status_code=400)
        return cls(config=base.model_copy(update={
            "ARK_API_KEY": user_settings.get("ark_api_key") or "",
        }))

    def _build_prompt(
        self, is_video: bool, tag_mode: TagMode = "default",
        custom_prompt: Optional[str] = None,
    ) -> str:
        if tag_mode == "default":
            if custom_prompt is not None and custom_prompt.strip():
                raise ServiceError("ark", "invalid_request", status_code=400)
            return _build_default_prompt(is_video)
        if tag_mode != "custom":
            raise ServiceError("ark", "invalid_request", status_code=400)
        prompt = custom_prompt.strip() if custom_prompt is not None else ""
        if not prompt or len(prompt) > MAX_CUSTOM_TAG_PROMPT_LENGTH:
            raise ServiceError("ark", "invalid_request", status_code=400)
        return f"{prompt}\n\n{CUSTOM_TAG_OUTPUT_CONTRACT}"

    async def generate_tags(
        self, tos_url: str, signed_url: Optional[str] = None,
        model: Optional[str] = None, api_key: Optional[str] = None,
        tag_mode: TagMode = "default", custom_prompt: Optional[str] = None,
    ) -> List[Dict]:
        if model is not None and model != self.default_model:
            raise ServiceError("ark", "invalid_request", status_code=400)
        kind = media_kind(tos_url)
        url = validate_media_url(signed_url if signed_url is not None else tos_url, kind)
        prompt = self._build_prompt(kind == "video", tag_mode, custom_prompt)
        data = await self._client.post("/responses", {
            "model": self.default_model,
            "stream": False,
            "input": [{
                "role": "user",
                "content": [
                    {"type": f"input_{kind}", f"{kind}_url": url},
                    {"type": "input_text", "text": prompt},
                ],
            }],
        }, api_key=api_key)
        return self._parse_tag_response(
            response_text(data), request_id=data.get("id"), tag_mode=tag_mode,
        )

    def _parse_tag_response(
        self, text: str, *, request_id: Optional[str] = None,
        tag_mode: TagMode = "default",
    ) -> List[Dict]:
        """非法 JSON 或标签结构不能伪装为空标签成功；合法空数组允许返回。"""
        try:
            if tag_mode not in ("default", "custom"):
                raise ValueError
            data = strict_json_loads(text)
            if (
                not isinstance(data, dict) or not isinstance(data.get("tags"), list)
                or (tag_mode == "custom" and set(data) != {"tags"})
            ):
                raise ValueError
            validated_tags = []
            seen = set()
            for tag in data["tags"]:
                if not isinstance(tag, dict):
                    raise ValueError
                if tag_mode == "custom" and set(tag) != {
                    "category", "tag", "confidence",
                }:
                    raise ValueError
                category = tag.get("category")
                tag_name = tag.get("tag") or tag.get("tag_name")
                confidence = tag.get("confidence", 0.5)
                if (
                    not isinstance(category, str) or not isinstance(tag_name, str)
                    or isinstance(confidence, bool) or not isinstance(confidence, (int, float))
                ):
                    raise ValueError
                confidence = float(confidence)
                if not math.isfinite(confidence):
                    raise ValueError
                if tag_mode == "custom":
                    category = category.strip()
                    tag_name = tag_name.strip()
                    if (
                        not category or not tag_name
                        or len(category) > 50 or len(tag_name) > 100
                    ):
                        raise ValueError
                if confidence < 0.5:
                    continue
                if (
                    tag_mode == "default"
                    and tag_name not in self.tag_system.get(category, [])
                ):
                    continue
                key = (category, tag_name)
                if key not in seen:
                    seen.add(key)
                    validated_tags.append({
                        "category": category, "tag_name": tag_name,
                        "confidence": min(1.0, confidence),
                    })
            return validated_tags
        except (ValueError, TypeError, OverflowError, RecursionError):
            raise invalid_response(request_id) from None

    def get_tag_system(self) -> Dict[str, List[str]]:
        return {key: list(values) for key, values in self.tag_system.items()}

    async def batch_generate_tags(self, media_urls: List[str], get_signed_url_func=None,
                                  api_key: Optional[str] = None,
                                  tag_mode: TagMode = "default",
                                  custom_prompt: Optional[str] = None) -> Dict:
        results = {}
        for url in media_urls:
            try:
                signed = await get_signed_url_func(url) if get_signed_url_func else None
                tags = await self.generate_tags(
                    url, signed, api_key=api_key, tag_mode=tag_mode,
                    custom_prompt=custom_prompt,
                )
                results[url] = {"tags": tags, "status": "success"}
            except Exception as exc:
                error = exc if isinstance(exc, ServiceError) else ServiceError("ark", "unavailable")
                results[url] = {"tags": [], "status": "failed", "error": str(error)}
        return results

    async def check_connection(self, api_key: Optional[str] = None) -> dict:
        """显式付费连通测试，仅验证指定模型文本响应，不冒充视频能力验收。"""
        data = await self._client.post("/responses", {
            "model": self.default_model,
            "stream": False,
            "input": [{"role": "user", "content": [
                {"type": "input_text", "text": 'Return exactly this JSON object: {"tags":[]}'},
            ]}],
        }, api_key=api_key)
        self._parse_tag_response(response_text(data), request_id=data.get("id"))
        return {"service": "ark", "status": "ok", "model": self.default_model}

    async def aclose(self) -> None:
        await self._client.aclose()


tag_service = TagService(client=ark_client)
