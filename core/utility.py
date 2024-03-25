"""
Jovimetrix - http://www.github.com/amorano/jovimetrix
Utility
"""

import io
import os
import json
import glob
import base64
import random
import shutil
from enum import Enum
from typing import Any
from pathlib import Path
from uuid import uuid4
from itertools import zip_longest

import torch
import numpy as np
from PIL import Image
import matplotlib.pyplot as plt
from loguru import logger

from comfy.utils import ProgressBar
from folder_paths import get_output_directory

from Jovimetrix import comfy_message, load_help, parse_reset, JOVBaseNode, \
    WILDCARD, ROOT

from Jovimetrix.sup.lexicon import Lexicon
from Jovimetrix.sup.util import parse_dynamic, path_next, parse_parameter, \
    zip_longest_fill

from Jovimetrix.sup.image import  cv2tensor,  image_convert, \
    tensor2pil, tensor2cv, pil2tensor, image_load, image_formats, image_diff, \
    MIN_IMAGE_SIZE

# =============================================================================

JOV_CATEGORY = "UTILITY"

FORMATS = ["gif", "png", "jpg"]
if (JOV_GIFSKI := os.getenv("JOV_GIFSKI", None)) is not None:
    if not os.path.isfile(JOV_GIFSKI):
        logger.error(f"gifski missing [{JOV_GIFSKI}]")
        JOV_GIFSKI = None
    else:
        FORMATS = ["gifski"] + FORMATS
        logger.info("gifski support")
else:
    logger.warning("no gifski support")

class EnumBatchMode(Enum):
    MERGE = 30
    PICK = 10
    SLICE = 15
    INDEX_LIST = 20
    RANDOM = 5

# =============================================================================

class AkashicData:
    def __init__(self, **kw) -> None:
        for k, v in kw.items():
            setattr(self, k, v)

class AkashicNode(JOVBaseNode):
    NAME = "AKASHIC (JOV) 📓"
    CATEGORY = f"JOVIMETRIX 🔺🟩🔵/{JOV_CATEGORY}"
    HELP_URL = f"{JOV_CATEGORY}#-akashic"
    DESC = "Display the top level attributes of an output."
    DESCRIPTION = load_help(NAME, CATEGORY, DESC, HELP_URL)
    RETURN_TYPES = (WILDCARD, 'AKASHIC', )
    RETURN_NAMES = (Lexicon.PASS_OUT, Lexicon.IO)
    OUTPUT_NODE = True
    SORT = 10

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        d = {
        "required": {},
        "optional": {
            Lexicon.PASS_IN: (WILDCARD, {})
        }}
        return Lexicon._parse(d, cls.HELP_URL)

    def __parse(self, val) -> dict[str, list[Any]]:
        if isinstance(val, dict):
            result = "{"
            for k, v in val.items():
                result["text"] += f"{k}:{self.__parse(v)}, "
            return "text", [result[:-2] + "}"]
        elif isinstance(val, (tuple, set, list,)):
            result = "("
            for v in val:
                result += f"{self.__parse(v)}, "
            return "text", [result[:-2] + ")"]
        elif isinstance(val, str):
             return "text", [val]
        elif isinstance(val, bool):
            return "text", ["True" if val else "False"]
        elif isinstance(val, torch.Tensor):
            # logger.debug(f"Tensor: {val.shape}")
            ret = []
            if not isinstance(val, (list, tuple, set,)):
                val = [val]
            for img in val:
                img = tensor2pil(img)
                buffered = io.BytesIO()
                img.save(buffered, format="PNG")
                img = base64.b64encode(buffered.getvalue())
                img = "data:image/png;base64," + img.decode("utf-8")
                ret.append(img)
            return "b64_images", ret
        else:
            # no clue what I am....
            meh = ''.join(repr(type(val)).split("'")[1:2])
            return "text", [meh]

    def run(self, **kw) -> tuple[Any, Any]:
        o = kw.get(Lexicon.PASS_IN, None)
        output = {"ui": {"b64_images": [], "text": []}}
        if o is None:
            output["ui"]["result"] = (o, {}, )
            return output

        for v in kw.values():
            who, data = self.__parse(v)
            output["ui"][who].extend(data)

        ak = AkashicData(image=output["ui"]["b64_images"], text=output["ui"]["text"] )
        output["result"] = (o, ak)
        return output

class ValueGraphNode(JOVBaseNode):
    NAME = "VALUE GRAPH (JOV) 📈"
    CATEGORY = f"JOVIMETRIX 🔺🟩🔵/{JOV_CATEGORY}"
    HELP_URL = f"{JOV_CATEGORY}#-value-graph"
    DESC = "Graphs historical execution run values."
    DESCRIPTION = load_help(NAME, CATEGORY, DESC, HELP_URL)
    RETURN_TYPES = ("IMAGE", )
    RETURN_NAMES = (Lexicon.IMAGE, )
    SORT = 15

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        d = {
        "required": {},
        "optional": {
            Lexicon.RESET: ("BOOLEAN", {"default": False}),
            Lexicon.VALUE: ("INT", {"default": 60, "min": 0, "tooltip":"Number of values to graph and display"}),
            Lexicon.WH: ("VEC2", {"default": (MIN_IMAGE_SIZE, MIN_IMAGE_SIZE), "step": 1, "label": [Lexicon.W, Lexicon.H]})
        },
        "hidden": {
            "ident": "UNIQUE_ID"
        }}
        return Lexicon._parse(d, cls.HELP_URL)

    @classmethod
    def IS_CHANGED(cls, **kw) -> float:
        return float("nan")

    def __init__(self, *arg, **kw) -> None:
        super().__init__(*arg, **kw)
        self.__history = []
        self.__fig, self.__ax = plt.subplots(figsize=(5.12, 5.12))

    def run(self, ident, **kw) -> tuple[torch.Tensor]:
        slice = kw.get(Lexicon.VALUE, [60])
        wihi = parse_parameter(Lexicon.WH, kw, (MIN_IMAGE_SIZE, MIN_IMAGE_SIZE), zero=0.001)[0]
        accepted = [bool, int, float, np.float16, np.float32, np.float64]
        if parse_reset(ident) > 0 or kw.get(Lexicon.RESET, False):
            self.__history = []
        longest_edge = 0
        dynamic = parse_dynamic(Lexicon.UNKNOWN, kw)
        params = [tuple(x) for x in zip_longest_fill(dynamic, slice)]
        pbar = ProgressBar(len(params))
        for idx, (val, slice) in enumerate(params):
            if isinstance(val, (set, tuple,)):
                val = list(val)
            if not isinstance(val, (list, )):
                val = [val]
            val = [v if type(v) in accepted else 0 for v in val]
            while len(self.__history) <= idx:
                self.__history.append([])
            self.__history[idx].extend(val)
            stride = max(0, -slice + len(self.__history[idx]) + 1)
            longest_edge = max(longest_edge, stride)
            self.__history[idx] = self.__history[idx][stride:]
            pbar.update_absolute(idx)

        self.__history = self.__history[:idx+1]
        self.__ax.clear()
        for i, h in enumerate(self.__history):
            self.__ax.plot(h, color="rgbcymk"[i])

        width, height = wihi
        wihi = (width / 100., height / 100.)
        self.__fig.set_figwidth(wihi[0])
        self.__fig.set_figheight(wihi[1])
        self.__fig.canvas.draw_idle()
        buffer = io.BytesIO()
        self.__fig.savefig(buffer, format="png")
        buffer.seek(0)
        image = Image.open(buffer)
        return (pil2tensor(image),)

class RouteNode(JOVBaseNode):
    NAME = "ROUTE (JOV) 🚌"
    CATEGORY = f"JOVIMETRIX 🔺🟩🔵/{JOV_CATEGORY}"
    HELP_URL = f"{JOV_CATEGORY}#-route"
    DESC = "Pass all data because the default is broken on connection."
    DESCRIPTION = load_help(NAME, CATEGORY, DESC, HELP_URL)
    INPUT_IS_LIST = True
    OUTPUT_IS_LIST = (True, )
    RETURN_TYPES = (WILDCARD, )
    RETURN_NAMES = (Lexicon.PASS_OUT, )
    SORT = 5

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        d = {
        "required": {},
        "optional": {
            Lexicon.PASS_IN: (WILDCARD, {})
        }}
        return Lexicon._parse(d, cls.HELP_URL)

    def run(self, **kw) -> tuple[Any, Any]:
        o = kw.get(Lexicon.PASS_IN, None)
        return (o, )

class QueueNode(JOVBaseNode):
    NAME = "QUEUE (JOV) 🗃"
    CATEGORY = f"JOVIMETRIX 🔺🟩🔵/{JOV_CATEGORY}"
    HELP_URL = f"{JOV_CATEGORY}#-queue"
    DESC = "Cycle lists of images files or strings for node inputs."
    DESCRIPTION = load_help(NAME, CATEGORY, DESC, HELP_URL)
    INPUT_IS_LIST = False
    RETURN_TYPES = (WILDCARD, WILDCARD, "STRING", "INT", "INT", )
    RETURN_NAMES = (Lexicon.ANY, Lexicon.QUEUE, Lexicon.CURRENT, Lexicon.INDEX, Lexicon.TOTAL, )
    OUTPUT_IS_LIST = (False, True, False, False, False, )
    VIDEO_FORMATS = ['.webm', '.mp4', '.avi', '.wmv', '.mkv', '.mov', '.mxf']
    SORT = 0

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        d = {
        "required": {},
        "optional": {
            Lexicon.QUEUE: ("STRING", {"multiline": True, "default": ""}),
            Lexicon.VALUE: ("INT", {"min": 0, "default": 0, "step": 1, "tooltip": "the current index for the current queue item"}),
            Lexicon.WAIT: ("BOOLEAN", {"default": False, "tooltip":"Hold the item at the current queue index"}),
            Lexicon.RESET: ("BOOLEAN", {"default": False, "tooltip":"reset the queue back to index 1"}),
        },
        "hidden": {
            "ident": "UNIQUE_ID"
        }}
        return Lexicon._parse(d, cls.HELP_URL)

    @classmethod
    def IS_CHANGED(cls) -> float:
        return float("nan")

    def __init__(self) -> None:
        self.__index = 0
        self.__q = None
        self.__index_last = None
        self.__len = 0
        self.__previous = None
        self.__last_q_value = {}

    def __parse(self, data) -> list:
        entries = []
        for line in data.strip().split('\n'):
            parts = [part.strip() for part in line.split(',')]
            count = 1

            try: count = int(parts[-1])
            except: pass

            data = [parts[0]]
            path = Path(parts[0])
            path2 = Path(ROOT / parts[0])
            if path.is_dir() or path2.is_dir():
                philter = parts[1].split(';') if len(parts) > 1 and isinstance(parts[1], str) else image_formats()
                philter.extend(self.VIDEO_FORMATS)
                path = path if path.is_dir() else path2
                file_names = [file.name for file in path.iterdir() if file.is_file()]
                new_data = [str(path / fname) for fname in file_names if any(fname.endswith(pat) for pat in philter)]
                if len(new_data):
                    data = new_data
            elif path.is_file() or path2.is_file():
                path = path if path.is_file() else path2
                path = str(path.resolve())
                if path.lower().endswith('.txt'):
                    with open(path, 'r', encoding='utf-8') as f:
                        data = f.read().split('\n')
                else:
                    data = [path]
            elif len(results := glob.glob(str(path2))) > 0:
                data = [x.replace('\\\\', '/') for x in results]

            if len(data) and count > 0:
                entries.extend(data * count)
        return entries

    def run(self, ident, **kw) -> None:

        def process(q_data: str) -> tuple[torch.Tensor, torch.Tensor] | str | dict:
            # single Q cache to skip loading single entries over and over
            if (val := self.__last_q_value.get(q_data, None)) is not None:
                return val
            if not os.path.isfile(q_data):
                return q_data
            _, ext = os.path.splitext(q_data)
            if ext in image_formats():
                data = image_load(q_data)[0]
                self.__last_q_value[q_data] = cv2tensor(data)
            elif ext == '.json':
                with open(q_data, 'r', encoding='utf-8') as f:
                    self.__last_q_value[q_data] = json.load(f)
            return self.__last_q_value.get(q_data, q_data)

        # should work headless as well
        if parse_reset(ident) > 0 or kw.get(Lexicon.RESET, False):
            self.__q = None
            self.__index = 0

        if (new_val := kw.get(Lexicon.VALUE, self.__index)) > 0:
            self.__index = new_val

        if self.__q is None:
            # process Q into ...
            # check if folder first, file, then string.
            # entry is: data, <filter if folder:*.png,*.jpg>, <repeats:1+>
            q = kw.get(Lexicon.QUEUE, "")
            self.__q = self.__parse(q)
            self.__len = len(self.__q)
            self.__index_last = 0
            self.__previous = self.__q[0] if len(self.__q) else None
            if self.__previous:
                self.__previous = process(self.__previous)

        if (wait := kw.get(Lexicon.WAIT, False)) == True:
            self.__index = self.__index_last

        self.__index = max(0, self.__index) % self.__len
        current = self.__q[self.__index]
        data = self.__previous
        self.__index_last = self.__index
        info = f"QUEUE #{ident} [{current}] ({self.__index})"
        if wait == True:
            info += f" PAUSED"
        else:
            data = process(self.__q[self.__index])
            self.__index += 1

        self.__previous = data
        msg = {"id": ident,
               "c": current,
               "i": self.__index_last+1,
               "s": self.__len,
               "l": self.__q
        }
        comfy_message(ident, "jovi-queue-ping", msg)
        return data, self.__q, current, self.__index_last+1, self.__len,

class ExportNode(JOVBaseNode):
    NAME = "EXPORT (JOV) 📽"
    CATEGORY = f"JOVIMETRIX 🔺🟩🔵/{JOV_CATEGORY}"
    HELP_URL = f"{JOV_CATEGORY}#-export"
    DESC = "Take your frames out static or animated (GIF)"
    DESCRIPTION = load_help(NAME, CATEGORY, DESC, HELP_URL)
    OUTPUT_NODE = True
    SORT = 80

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        d = {
        "required": {},
        "optional": {
            Lexicon.PIXEL: (WILDCARD, {}),
            Lexicon.PASS_OUT: ("STRING", {"default": get_output_directory()}),
            Lexicon.FORMAT: (FORMATS, {"default": FORMATS[0]}),
            Lexicon.PREFIX: ("STRING", {"default": ""}),
            Lexicon.OVERWRITE: ("BOOLEAN", {"default": False}),
            # GIF ONLY
            Lexicon.OPTIMIZE: ("BOOLEAN", {"default": False}),
            # GIFSKI ONLY
            Lexicon.QUALITY: ("INT", {"default": 90, "min": 1, "max": 100}),
            Lexicon.QUALITY_M: ("INT", {"default": 100, "min": 1, "max": 100}),
            # GIF OR GIFSKI
            Lexicon.FPS: ("INT", {"default": 20, "min": 1, "max": 60}),
            # GIF OR GIFSKI
            Lexicon.LOOP: ("INT", {"default": 0, "min": 0}),
        }}
        return Lexicon._parse(d, cls.HELP_URL)
    SORT = 2000

    def run(self, **kw) -> None:
        pA = parse_parameter(kw.get(Lexicon.PIXEL, None))
        suffix = kw.get(Lexicon.PREFIX, [""])[0]
        if suffix == "":
            suffix = uuid4().hex[:16]

        output_dir = kw.get(Lexicon.PASS_OUT, [""])[0]
        format = kw.get(Lexicon.FORMAT, ["gif"])[0]
        overwrite = kw.get(Lexicon.OVERWRITE, False)[0]
        optimize = kw.get(Lexicon.OPTIMIZE, [False])[0]
        quality = kw.get(Lexicon.QUALITY, [0])[0]
        motion = kw.get(Lexicon.QUALITY_M, [0])[0]
        fps = kw.get(Lexicon.FPS, [0])[0]
        loop = kw.get(Lexicon.LOOP, [0])[0]

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        def output(extension) -> Path:
            path = output_dir / f"{suffix}.{extension}"
            if not overwrite and os.path.isfile(path):
                path = str(output_dir / f"{suffix}_%s.{extension}")
                path = path_next(path)
            return path

        empty = Image.new("RGB", (MIN_IMAGE_SIZE, MIN_IMAGE_SIZE))
        images = [tensor2pil(i).convert("RGB") if i is not None else empty for i in pA]
        if format == "gifski":
            root = output_dir / f"{suffix}_{uuid4().hex[:16]}"
            try:
                root.mkdir(parents=True, exist_ok=True)
                for idx, i in enumerate(images):
                    fname = str(root / f"{suffix}_{idx}.png")
                    i.save(fname)
            except Exception as e:
                logger.warning(output_dir)
                logger.error(str(e))
                return

            out = output('gif')
            fps = f"--fps {fps}" if fps > 0 else ""
            q = f"--quality {quality}"
            mq = f"--motion-quality {motion}"
            cmd = f"{JOV_GIFSKI} -o {out} {q} {mq} {fps} {str(root)}/{suffix}_*.png"
            logger.info(cmd)
            try:
                os.system(cmd)
            except Exception as e:
                logger.warning(cmd)
                logger.error(str(e))

            shutil.rmtree(root)

        elif format == "gif":
            images[0].save(
                output('gif'),
                append_images=images[1:],
                disposal=2,
                duration=1 / fps * 1000 if fps else 0,
                loop=loop,
                optimize=optimize,
                save_all=True,
            )
        else:
            for img in images:
                img.save(output(format), optimize=optimize)

        return ()

class ImageDiffNode(JOVBaseNode):
    NAME = "IMAGE DIFF (JOV) 📏"
    CATEGORY = f"JOVIMETRIX 🔺🟩🔵/{JOV_CATEGORY}"
    HELP_URL = f"{JOV_CATEGORY}#-image-diff"
    DESC = "Explicitly show the differences between two images via self-similarity index."
    DESCRIPTION = load_help(NAME, CATEGORY, DESC, HELP_URL)
    RETURN_TYPES = ("IMAGE", "IMAGE", "MASK", "MASK", "FLOAT", )
    RETURN_NAMES = (Lexicon.IN_A, Lexicon.IN_B, Lexicon.DIFF, Lexicon.THRESHOLD, Lexicon.FLOAT, )
    OUTPUT_IS_LIST = (False, False, False, False, True, )
    SORT = 90

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        d = {
        "required": {},
        "optional": {
            Lexicon.PIXEL_A: (WILDCARD, {}),
            Lexicon.PIXEL_B: (WILDCARD, {}),
            Lexicon.THRESHOLD: ("FLOAT", {"default": 0.5, "min": 0, "max": 1, "step": 0.01}),
        }}
        return Lexicon._parse(d, cls.HELP_URL)

    def run(self, **kw) -> tuple[Any, Any]:
        pA = parse_parameter(kw.get(Lexicon.PIXEL_A, None))
        pB = parse_parameter(kw.get(Lexicon.PIXEL_B, None))
        th = kw.get(Lexicon.THRESHOLD, [0])
        results = []
        params = [tuple(x) for x in zip_longest_fill(pA, pB, th)]
        pbar = ProgressBar(len(params))
        for idx, (pA, pB, th) in enumerate(params):
            pA = tensor2cv(pA)
            pA = tensor2cv(pB)
            a, b, d, t, s = image_diff(pA, pB, int(th * 255))
            d = image_convert(d, 1)
            t = image_convert(t, 1)
            results.append([cv2tensor(a), cv2tensor(b), cv2tensor(d), cv2tensor(t), s])
            pbar.update_absolute(idx)
        return [list(a) for a in zip(*results)]

class ArrayNode(JOVBaseNode):
    NAME = "ARRAY (JOV) 📚"
    CATEGORY = f"JOVIMETRIX 🔺🟩🔵/{JOV_CATEGORY}"
    HELP_URL = f"{JOV_CATEGORY}#-array"
    DESC = "Make, merge, splice or split a batch or list."
    DESCRIPTION = load_help(NAME, CATEGORY, DESC, HELP_URL)
    INPUT_IS_LIST = False
    OUTPUT_IS_LIST = (False, False, True,)
    RETURN_TYPES = ("INT", WILDCARD, WILDCARD,)
    RETURN_NAMES = (Lexicon.VALUE, Lexicon.ANY, Lexicon.LIST,)
    SORT = 50

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        d = {
        "required": {},
        "optional": {
            Lexicon.BATCH_MODE: (EnumBatchMode._member_names_, {"default": EnumBatchMode.MERGE.name, "tooltip":"select a single index, specific range, custom index list or randomized"}),
            Lexicon.INDEX: ("INT", {"default": 0, "min": 0, "step": 1}),
            Lexicon.RANGE: ("VEC3", {"default": (0, 0, 1)}),
            Lexicon.STRING: ("STRING", {"default": ""}),
            Lexicon.SEED: ("INT", {"default": 0, "min": 0, "step": 1}),
            Lexicon.FLIP: ("BOOLEAN", {"default": False}),
            Lexicon.BATCH_CHUNK: ("INT", {"default": 0, "min": 0, "step": 1}),
        }}
        return Lexicon._parse(d, cls.HELP_URL)

    @classmethod
    def batched(cls, iterable, chunk_size, expand:bool=False, fill:Any=None):
        if expand:
            iterator = iter(iterable)
            return zip_longest(*[iterator] * chunk_size, fillvalue=fill)
        return [iterable[i: i + chunk_size] for i in range(0, len(iterable), chunk_size)]
        # return iter(lambda: tuple(islice(iterator, chunk_size)), tuple())

    def run(self, **kw) -> tuple[int, list]:
        batch = parse_dynamic(Lexicon.UNKNOWN, kw)
        mode = kw.get(Lexicon.BATCH_MODE, EnumBatchMode.MERGE)
        flip = kw.get(Lexicon.FLIP, False)
        chunk = kw.get(Lexicon.BATCH_CHUNK, 0)
        extract = []
        # track latents since they need to be added back to dict['samples']
        latents = []
        full = []
        for b in batch:
            if isinstance(b, dict) and "samples" in b:
                # latents are batched in the x.samples key
                data = b["samples"]
                full.extend([{"samples": [i]} for i in data])
                extract.extend(data)
                latents.extend([True] * len(data))
            elif isinstance(b, torch.Tensor):
                data = [i for i in batch]
                full.extend(data)
                extract.extend(data)
                latents.extend([False] * len(data))
            elif isinstance(b, (list, set, tuple,)):
                full.extend(b)
                extract.extend(b)
                latents.extend([False] * len(b))
            else:
                full.append(b)
                extract.append(b)
                latents.append(False)

        if mode == EnumBatchMode.PICK:
            index = kw.get(Lexicon.BATCH_CHUNK, 0)
            index = index if index < len(extract) else -1
            extract = [extract[index]]
            if latents[index]:
                extract = {"samples": extract}
        elif mode == EnumBatchMode.SLICE:
            slice_range = parse_parameter(Lexicon.RANGE, kw, (0, 0, 1))[0]
            start, end, step = slice_range
            end = len(extract) if end == 0 else end
            data = extract[start:end:step]
            latents = latents[start:end:step]
            extract = []
            for i, lat in enumerate(latents):
                dat = data[i]
                if lat:
                    dat = {"samples": [dat]}
                extract.append(dat)
        elif mode == EnumBatchMode.RANDOM:
            seed = kw.get(Lexicon.SEED, 0)
            random.seed(seed)
            full = random.choices(full)
            idx = random.randrange(0, len(extract))
            extract = [extract[idx]]
            if latents[idx]:
                extract = {"samples": extract}
        elif mode == EnumBatchMode.INDEX_LIST:
            indices = kw.get(Lexicon.STRING, [""]).split(",")
            data = [extract[i:j] for i, j in zip([0]+indices, indices+[None])]
            latents = [latents[i:j] for i, j in zip([0]+indices, indices+[None])]
            extract = []
            for i, lat in enumerate(latents):
                dat = data[i]
                if lat:
                    dat = {"samples": [dat]}
                extract.append(dat)

        if flip and len(extract) > 1:
            extract = extract[::-1]

        if chunk > 0:
            extract = [e for e in self.batched(extract, chunk)]
        return (len(extract), extract, full,)

"""
class HistogramNode(JOVImageSimple):
    NAME = "HISTOGRAM (JOV) 👁‍🗨"
    CATEGORY = f"JOVIMETRIX 🔺🟩🔵/{JOV_CATEGORY}"
    DESC = "Histogram"
    DESCRIPTION = load_help(NAME, CATEGORY, DESC, HELP_URL)
    RETURN_TYPES = ("IMAGE", )
    RETURN_NAMES = (Lexicon.IMAGE,)
    OUTPUT_IS_LIST = (True,)
    SORT = 40

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        d = {
        "required": {},
        "optional": {
            Lexicon.PIXEL: (WILDCARD, {}),
        }}
        return Lexicon._parse(d, cls.HELP_URL)

    def run(self, **kw) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        pA = parse_parameter(kw.get(Lexicon.PIXEL, None))
        params = [tuple(x) for x in zip_longest_fill(pA,)]
        images = []
        pbar = ProgressBar(len(params))
        for idx, (pA, ) in enumerate(params):
            pA = image_histogram(pA)
            pA = image_histogram_normalize(pA)
            images.append(cv2tensor(pA))
            pbar.update_absolute(idx)
        return list(zip(*images))
"""

class GenuflectNode(JOVBaseNode):
    NAME = "GENUFLECT (JOV) 📏"
    CATEGORY = f"JOVIMETRIX 🔺🟩🔵/{JOV_CATEGORY}"
    HELP_URL = f"{JOV_CATEGORY}#-genuflect"
    DESC = "Shill node to test input and outputs"
    DESCRIPTION = load_help(NAME, CATEGORY, DESC, HELP_URL)
    OUTPUT_IS_LIST = (False, )
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = (Lexicon.IN_A, )
    SORT = 200

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        d = {
        "required": {},
        "optional": {
            Lexicon.PIXEL_A: (WILDCARD, {}),
        }}
        return Lexicon._parse(d, cls.HELP_URL)

    def run(self, **kw) -> tuple[Any, Any]:
        pA = parse_parameter(kw.get(Lexicon.PIXEL_A, None))

        results = []
        params = [tuple(x) for x in zip_longest_fill(pA,)]
        pbar = ProgressBar(len(params))
        for idx, (pA, ) in enumerate(params):
            pA = tensor2cv(pA)
            results.append(cv2tensor(pA))
            pbar.update_absolute(idx)
        return [list(a) for a in zip(*results)]