"""
OCR 辅助模块
截取企业微信搜索结果区域，识别联系人部门信息并匹配目标单位。
"""

import os
import sys
import shutil

import pyautogui
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── 搜索结果截图区域（基于 2560x1600 分辨率）──────────────────
# 根据截图观察：搜索结果第一条大约在窗口上方 160~280px 区域
# 这里截取的是部门文字所在的那一行
# 如果识别不准，可以适当调整 TOP/BOTTOM
RESULT_LEFT   = 0
RESULT_TOP    = 155
RESULT_RIGHT  = 1400
RESULT_BOTTOM = 290


class WeComOCR:
    """企业微信搜索结果 OCR 识别器"""

    def __init__(self):
        self._ocr = None

    # def _get_ocr(self):
    #     """懒加载 PaddleOCR，避免启动时拖慢速度"""
    #     if self._ocr is None:
    #         from paddleocr import PaddleOCR
    #         self._ocr = PaddleOCR(
    #             use_angle_cls=False,  # 搜索结果都是正向文字，不需要角度检测
    #             lang="ch",
    #             show_log=False,       # 关闭 PaddleOCR 的日志输出
    #         )
    #         logger.info("PaddleOCR 初始化完成")
    #     return self._ocr
    def _get_ocr(self):
        if self._ocr is None:
            from paddleocr import PaddleOCR

            # 优先使用随程序打包的本地模型（离线可用），避免首次运行从外网下载模型失败。
            kwargs = {"lang": "ch", "show_log": False}
            model_dirs = self._local_model_dirs()
            if all(d is not None for d in model_dirs):
                det_dir, rec_dir, cls_dir = model_dirs
                kwargs.update(
                    det_model_dir=det_dir,
                    rec_model_dir=rec_dir,
                    cls_model_dir=cls_dir,
                )
                logger.info("使用本地 OCR 模型: %s", ", ".join(os.path.basename(d) for d in model_dirs))
            else:
                logger.warning("未找到内置 OCR 模型目录，将尝试在线下载（可能因网络受限失败）")

            try:
                self._ocr = PaddleOCR(**kwargs)
            except SystemExit:
                # paddleocr 下载模型失败时会直接 sys.exit(0)，在窗口程序里会静默闪退，这里转为可读错误
                logger.error("PaddleOCR 模型初始化被中断（模型缺失或下载失败）")
                raise RuntimeError(
                    "OCR 模型初始化失败：未找到内置模型且在线下载失败。"
                    "请确认程序自带的 models 目录完整，或重新打包（build.bat 会自动下载模型）。"
                )
            except Exception as e:
                logger.error("PaddleOCR 初始化失败: %s", e)
                raise RuntimeError("PaddleOCR 初始化失败，请检查程序自带的 models 目录") from e

            logger.info("PaddleOCR 初始化完成")

        return self._ocr

    @staticmethod
    def _model_base() -> str:
        """模型根目录：frozen 时位于 sys._MEIPASS/models，开发环境位于项目根 models/。"""
        if getattr(sys, "frozen", False):
            return os.path.join(sys._MEIPASS, "models")
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models"
        )

    @classmethod
    def _model_complete(cls, model_dir: str) -> bool:
        return (
            os.path.isfile(os.path.join(model_dir, "inference.pdmodel"))
            and os.path.isfile(os.path.join(model_dir, "inference.pdiparams"))
        )

    @classmethod
    def _local_model_dir(cls, name: str) -> Optional[str]:
        """
        返回可被 Paddle 加载的本地模型目录；未找到（文件不完整）返回 None。

        注意：Paddle 的 C++ 推理引擎在 Windows 上无法打开含中文等非 ASCII 字符的路径，
        因此当模型所在路径含非 ASCII 字符时，会先把模型复制到 %PROGRAMDATA% 下的
        ASCII 目录（C:\\ProgramData\\LingShouOCR\\models）再返回该目录，保证离线可用。
        """
        path = os.path.join(cls._model_base(), name)
        if not cls._model_complete(path):
            return None
        if any(ord(c) > 127 for c in path):
            return cls._ensure_ascii_copy(name)
        return path

    @classmethod
    def _ensure_ascii_copy(cls, name: str) -> Optional[str]:
        """把模型复制到 ASCII 目录并返回其路径；复制失败返回 None。"""
        src = os.path.join(cls._model_base(), name)
        dst_root = os.path.join(
            os.environ.get("PROGRAMDATA", "C:/ProgramData"), "LingShouOCR", "models"
        )
        try:
            os.makedirs(dst_root, exist_ok=True)
        except OSError as e:
            logger.error("创建模型缓存目录失败 %s: %s", dst_root, e)
            return None
        dst = os.path.join(dst_root, name)
        if cls._model_complete(dst):
            return dst
        try:
            if os.path.isdir(dst):
                shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(src, dst)
            logger.info("已将 OCR 模型复制到 ASCII 目录: %s", dst)
        except OSError as e:
            logger.error("复制 OCR 模型到 ASCII 目录失败: %s", e)
            return None
        return dst if cls._model_complete(dst) else None

    def _local_model_dirs(self):
        return (
            self._local_model_dir("ch_PP-OCRv4_det_infer"),
            self._local_model_dir("ch_PP-OCRv4_rec_infer"),
            self._local_model_dir("ch_ppocr_mobile_v2.0_cls_infer"),
        )

    def capture_result_area(self) -> object:
        """根据企业微信窗口实际位置截取搜索结果区域"""
        import pygetwindow as gw

        windows = [
            w for w in gw.getAllWindows()
            if w.title.strip() == "全局搜索"
        ]

        if not windows:
            raise RuntimeError("未找到全局搜索窗口")

        win = windows[0]

        left = win.left
        top = win.top

        # 只截左边约75%的宽度，排除右侧名片图标所在区域
        width = int(win.width * 0.75)
        height = win.height

        region = (left, top, width, height)
        screenshot = pyautogui.screenshot(region=region)
        return screenshot, region

    def read_department(self) -> str:
        """
        截图并识别搜索结果第一条的部门文字。
        返回识别到的完整文字，识别失败返回空字符串。
        """
        try:
            screenshot = self.capture_result_area()

            # 转为 numpy array 供 PaddleOCR 使用
            import numpy as np
            img_array = np.array(screenshot)

            ocr = self._get_ocr()
            result = ocr.ocr(img_array, cls=False)

            if not result or not result[0]:
                logger.warning("OCR 未识别到任何文字")
                return ""

            # 把所有识别到的文字拼在一起
            texts = [line[1][0] for line in result[0] if line[1][1] > 0.5]
            full_text = " ".join(texts)
            logger.info(f"OCR 识别结果: {full_text}")
            return full_text

        except Exception as e:
            logger.error(f"OCR 识别失败: {e}")
            return ""

    def match_unit(self, unit: str) -> bool:
        """
        识别搜索结果区域的文字，判断是否包含目标单位。

        Args:
            unit: 目标单位名称，如"信用卡中心"

        Returns:
            True = 匹配成功，可以回车进入聊天
            False = 不匹配，需要跳过
        """
        if not unit:
            # 没有填单位，不做验证，直接通过
            return True

        text = self.read_department()
        if not text:
            # OCR 识别失败，记录警告但放行，避免误杀
            logger.warning(f"OCR 识别失败，跳过单位验证，直接发送")
            return True

        matched = unit in text
        if matched:
            logger.info(f"单位匹配成功: {unit} in {text}")
        else:
            logger.warning(f"单位不匹配: 期望={unit}, 识别到={text}")
        return matched
    
    def extract_text_blocks(self):
        """
        OCR识别搜索结果区域，返回文字块及坐标
        """

        screenshot, region = self.capture_result_area()

        import numpy as np

        img_array = np.array(screenshot)


        ocr = self._get_ocr()

        result = ocr.ocr(img_array, cls=False)
        #test
        if not result:
            print("OCR 空结果")
            logger.info("OCR 空结果")
            return []

        print("\n===== OCR 识别结果 =====")
        logger.info("===== OCR 识别结果 =====")

        for line in result[0]:
            text = line[1][0]
            score = line[1][1]
            print(f"{text} ({score:.2f})")
            logger.info(f"{text} ({score:.2f})")

        print("========================\n")
        logger.info("========================\n")
        #test

        if not result or not result[0]:
            logger.warning("OCR 未识别到任何文字")
            return []

        blocks = []

        for line in result[0]:

            try:
                box = line[0]

                text = line[1][0].strip()

                score = line[1][1]

                if score < 0.6:
                    continue

                center_x = sum(p[0] for p in box) / 4
                center_y = sum(p[1] for p in box) / 4

                blocks.append({
                    "text": text,
                    "x": region[0] + center_x,
                    "y": region[1] + center_y
                })

            except Exception as e:
                logger.error(f"OCR解析失败: {e}")

        # blocks.sort(key=lambda item: item["y"])

        logger.info("========== OCR结果 ==========")

        for block in blocks:
            logger.info(
                f"y={block['y']:.0f} text={block['text']}"
            )

        logger.info("============================")

        return blocks

    # def find_contact(self, target_name: str, target_unit: str):
    #     blocks = self.extract_text_blocks()
    #     if not blocks:
    #         return None

    #     # 找最后一个"联系人"分类标题
    #     contact_section_idx = None
    #     for i, b in enumerate(blocks):
    #         if b["text"].strip() == "联系人":
    #             contact_section_idx = i

    #     print(f"联系人标题在第 {contact_section_idx} 个block")

    #     if contact_section_idx is None:
    #         return None

    #     blocks_after = blocks[contact_section_idx + 1:]

    #     print("===== blocks_after =====")
    #     for i, b in enumerate(blocks_after):
    #         print(f"  [{i}] text={b['text']}")
    #     print("========================")

    #     for i, b in enumerate(blocks_after):
    #         if target_name in b["text"]:
    #             if i + 1 >= len(blocks_after):
    #                 continue
    #             next_block = blocks_after[i + 1]
    #             print(f"姓名匹配: [{i}]{b['text']} → 下一块[{i+1}]{next_block['text']}")
    #             # 改成 j, bb，避免覆盖外层的 i, b
    #             for j, bb in enumerate(blocks_after):
    #                 print(f"  [{j}] text={bb['text']}  x={bb['x']:.0f}  y={bb['y']:.0f}")
    #             print(f">>> 开始判断: target_unit='{target_unit}' next_block_text='{next_block['text']}'")
    #             print(f">>> 判断结果: {target_unit in next_block['text']}")
    #             if target_unit in next_block["text"]:
    #                 print(f">>> 匹配成功，准备返回坐标")
    #                 return {"click_x": b["x"], "click_y": b["y"]}
    #             else:
    #                 print(f">>> 单位不符，跳过，继续找下一个")
    #                 continue

    #     return None
    def find_contact(self, target_name: str, target_unit: str):
        # 第一次扫描
        result = self._scan_and_match(target_name, target_unit)
        if result:
            return result

        # 没找到，检查是否有"查看全部"
        blocks = self.extract_text_blocks()
        see_all_block = next((b for b in blocks if "查看全部" in b["text"]), None)

        if not see_all_block:
            logger.warning(f"未找到联系人且无'查看全部': {target_name}")
            return None

        # 点击"查看全部"展开
        logger.info(f"点击'查看全部'展开联系人列表")
        import pyautogui as _pag
        _pag.click(see_all_block["x"], see_all_block["y"])
        import time
        time.sleep(1.0)

        # 展开后滚动扫描
        return self._scroll_and_match(target_name, target_unit)


    def _scan_and_match(self, target_name: str, target_unit: str, expanded: bool = False):
        """单次OCR扫描并匹配
        expanded: True表示已点击"查看全部"展开，False表示初始搜索结果
        """
        blocks = self.extract_text_blocks()
        if not blocks:
            return None

        if expanded:
            # 展开后没有Tab标签，直接从第一个block开始匹配
            blocks_after = blocks
        else:
            # 初始搜索结果，需要找"联系人"分类标题
            contact_section_idx = None
            for i, b in enumerate(blocks):
                if b["text"].strip() == "联系人":
                    contact_section_idx = i
            if contact_section_idx is None:
                return None
            blocks_after = blocks[contact_section_idx + 1:]

        for i, b in enumerate(blocks_after):
            if target_name in b["text"]:
                if i + 1 >= len(blocks_after):
                    continue
                next_block = blocks_after[i + 1]
                if target_unit in next_block["text"]:
                    logger.info(f"找到联系人: {target_name} / {next_block['text']}")
                    return {"click_x": b["x"], "click_y": b["y"]}
                else:
                    continue

        return None


    def _scroll_and_match(self, target_name: str, target_unit: str):
        import pyautogui as _pag
        import time

        # 最多按50次↓键查找
        for attempt in range(50):
            result = self._scan_and_match(target_name, target_unit, expanded=True)
            if result:
                return result

            logger.info(f"第{attempt+1}次按↓查找")
            _pag.press("down")
            time.sleep(0.3)  # 等待高亮切换

        logger.warning(f"按↓50次后仍未找到: {target_name}")
        return None
# ── 单例，避免重复初始化 PaddleOCR ────────────────────────────
_wecom_ocr = None

def get_ocr() -> WeComOCR:
    global _wecom_ocr
    if _wecom_ocr is None:
        _wecom_ocr = WeComOCR()
    return _wecom_ocr