#!/usr/bin/env python3
import json
import time
import urllib.request
import uuid
from pathlib import Path


SERVER = "http://127.0.0.1:8188"
OUTPUT_ROOT = Path("/home/intern/Supervised 2D to 3D/vlm/experiments/comfyui_output")


def api_json(path, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{SERVER}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=30) as response:
        return json.load(response)


def main():
    workflow = {
        "1": {
            "class_type": "DiffusersLoader",
            "inputs": {"model_path": "sdxl-base-1.0"},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": "a small matte painted PVC anime figurine, studio product photo, white seamless background, front view",
                "clip": ["1", 1],
            },
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": "text, watermark, logo, border, multiple views, low quality",
                "clip": ["1", 1],
            },
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512, "batch_size": 1},
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 20260722,
                "steps": 8,
                "cfg": 6.0,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1.0,
                "model": ["1", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
            },
        },
        "6": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
        },
        "7": {
            "class_type": "SaveImage",
            "inputs": {
                "filename_prefix": "smoke/sdxl_local_gpu0",
                "images": ["6", 0],
            },
        },
    }

    submitted = api_json(
        "/prompt",
        {"prompt": workflow, "client_id": f"local-smoke-{uuid.uuid4()}"},
    )
    prompt_id = submitted["prompt_id"]
    deadline = time.monotonic() + 300

    while time.monotonic() < deadline:
        history = api_json(f"/history/{prompt_id}").get(prompt_id)
        if history:
            status = history.get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError(json.dumps(status, ensure_ascii=False))
            if status.get("completed"):
                images = history.get("outputs", {}).get("7", {}).get("images", [])
                if not images:
                    raise RuntimeError("Workflow completed without a saved image")
                for image in images:
                    path = OUTPUT_ROOT / image.get("subfolder", "") / image["filename"]
                    print(path.resolve())
                return
        time.sleep(1)

    raise TimeoutError(f"ComfyUI workflow {prompt_id} did not finish within 300 seconds")


if __name__ == "__main__":
    main()
