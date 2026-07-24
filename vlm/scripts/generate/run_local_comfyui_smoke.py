#!/usr/bin/env python3
"""
ComfyUI Local Smoke Test

This script validates that a local ComfyUI instance is running and can execute
a basic text-to-image generation workflow using SDXL.

ComfyUI API Protocol Overview:
------------------------------
ComfyUI exposes an HTTP REST API on port 8188 (by default). The workflow execution
model works as follows:

1. POST /prompt - Submit a workflow graph as JSON. The workflow is a dictionary
   where keys are node IDs and values define node type (class_type) and inputs.
   Inputs can reference other nodes' outputs using [node_id, output_index] tuples.

2. The server returns a prompt_id that uniquely identifies this execution.

3. GET /history/{prompt_id} - Poll this endpoint to check execution status.
   When the workflow completes, the history entry contains:
   - status.completed: True when done
   - status.status_str: "error" if failed
   - outputs: Dict mapping node IDs to their outputs (e.g., saved image metadata)

4. Images are saved to the ComfyUI output directory. The history response contains
   filenames and subfolders for retrieval.

How to Run:
-----------
1. Ensure ComfyUI is running locally on http://127.0.0.1:8188
2. Ensure the SDXL model "sdxl-base-1.0" is installed in ComfyUI's models directory
3. Run this script: python run_local_comfyui_smoke.py
4. On success, it prints the absolute path to the generated image file
5. On failure, it raises an exception with error details

Expected Output:
----------------
The script prints the absolute path to a generated 512x512 PNG image of an anime
figurine on a white background, saved to:
/home/intern/Supervised 2D to 3D/vlm/experiments/comfyui_output/smoke/sdxl_local_gpu0_*.png
"""
import json
import time
import urllib.request
import uuid
from pathlib import Path


SERVER = "http://127.0.0.1:8188"
OUTPUT_ROOT = Path("/home/intern/Supervised 2D to 3D/vlm/experiments/comfyui_output")


def api_json(path, payload=None):
    """
    Make an HTTP request to the ComfyUI API and return the JSON response.

    This function handles both GET requests (when payload is None) and POST requests
    (when payload is provided). It bypasses system proxies to ensure direct connection
    to the local ComfyUI server.

    Args:
        path: API endpoint path (e.g., "/prompt" or "/history/12345")
        payload: Optional dict to send as JSON in request body (for POST)

    Returns:
        Parsed JSON response as a Python dict

    Raises:
        urllib.error.URLError: If the server is unreachable
        json.JSONDecodeError: If response is not valid JSON
    """
    # Convert payload dict to JSON bytes if provided (POST), otherwise None (GET)
    data = None if payload is None else json.dumps(payload).encode("utf-8")

    # Build the request with proper Content-Type header for JSON
    request = urllib.request.Request(
        f"{SERVER}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
    )

    # Use ProxyHandler({}) to bypass system proxy settings for localhost connection
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    # Execute request with 30-second timeout and parse JSON response
    with opener.open(request, timeout=30) as response:
        return json.load(response)


def main():
    """
    Execute a smoke test workflow on the local ComfyUI instance.

    This function constructs a complete SDXL text-to-image workflow, submits it to
    ComfyUI, polls until completion, and prints the output image path.

    The workflow consists of 7 nodes connected in a graph:
    - Node 1: Load SDXL model and components (model, CLIP, VAE)
    - Node 2: Encode positive prompt using CLIP
    - Node 3: Encode negative prompt using CLIP
    - Node 4: Create empty latent image (noise tensor)
    - Node 5: Run K-sampler (diffusion denoising process)
    - Node 6: Decode latent to pixel image using VAE
    - Node 7: Save final image to disk

    Node connections are represented as [node_id, output_index] tuples:
    - ["1", 0] = model output from node 1
    - ["1", 1] = CLIP output from node 1
    - ["1", 2] = VAE output from node 1
    - ["2", 0] = positive conditioning from node 2
    - And so on...

    Raises:
        RuntimeError: If workflow execution fails or produces no output
        TimeoutError: If workflow doesn't complete within 300 seconds
    """
    # Define the workflow graph as a dictionary of nodes
    # Each node ID maps to its class_type (ComfyUI node type) and inputs
    workflow = {
        # Node 1: Load the SDXL diffusion model, CLIP text encoder, and VAE
        "1": {
            "class_type": "DiffusersLoader",
            "inputs": {"model_path": "sdxl-base-1.0"},
        },
        # Node 2: Encode the positive prompt into conditioning vectors
        # Uses CLIP from node 1's output slot 1
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": "a small matte painted PVC anime figurine, studio product photo, white seamless background, front view",
                "clip": ["1", 1],  # Connect to node 1's CLIP output
            },
        },
        # Node 3: Encode the negative prompt (what to avoid in generation)
        # Also uses CLIP from node 1's output slot 1
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": "text, watermark, logo, border, multiple views, low quality",
                "clip": ["1", 1],  # Connect to node 1's CLIP output
            },
        },
        # Node 4: Create an empty latent image (random noise) to start diffusion
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512, "batch_size": 1},
        },
        # Node 5: Run the K-sampler to denoise the latent image
        # This is the core diffusion process that generates the image
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 20260722,           # Fixed seed for reproducibility
                "steps": 8,                  # Number of denoising steps
                "cfg": 6.0,                  # Classifier-free guidance scale
                "sampler_name": "euler",     # Euler sampling algorithm
                "scheduler": "normal",       # Standard noise schedule
                "denoise": 1.0,              # Full denoising (1.0 = complete)
                "model": ["1", 0],           # Connect to node 1's model output
                "positive": ["2", 0],        # Connect to node 2's conditioning
                "negative": ["3", 0],        # Connect to node 3's conditioning
                "latent_image": ["4", 0],    # Connect to node 4's latent
            },
        },
        # Node 6: Decode the denoised latent into a pixel-space image
        "6": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["5", 0], "vae": ["1", 2]},  # Latent from node 5, VAE from node 1
        },
        # Node 7: Save the final decoded image to disk
        "7": {
            "class_type": "SaveImage",
            "inputs": {
                "filename_prefix": "smoke/sdxl_local_gpu0",  # Subfolder/prefix for output
                "images": ["6", 0],  # Connect to node 6's pixel image output
            },
        },
    }

    # Submit the workflow to ComfyUI's /prompt endpoint
    # The client_id is used for websocket notifications (not used in this script)
    submitted = api_json(
        "/prompt",
        {"prompt": workflow, "client_id": f"local-smoke-{uuid.uuid4()}"},
    )

    # Extract the prompt_id - this is the unique identifier for tracking this execution
    # All subsequent API calls use this ID to query status and results
    prompt_id = submitted["prompt_id"]

    # Set a 300-second (5-minute) deadline for workflow completion
    deadline = time.monotonic() + 300

    # Polling loop: repeatedly check the /history endpoint until workflow completes
    # The history endpoint returns execution status and output metadata
    while time.monotonic() < deadline:
        # GET /history/{prompt_id} returns the execution record for this specific workflow
        # If the workflow hasn't started yet, the response may not contain the prompt_id key
        history = api_json(f"/history/{prompt_id}").get(prompt_id)

        if history:
            # Extract the status object which contains completion/error information
            status = history.get("status", {})

            # Check if workflow execution failed
            if status.get("status_str") == "error":
                raise RuntimeError(json.dumps(status, ensure_ascii=False))

            # Check if workflow execution completed successfully
            # The "completed" flag is the key signal that processing is done
            if status.get("completed"):
                # Extract output metadata from node 7 (SaveImage node)
                # The outputs dict maps node IDs to their output data
                images = history.get("outputs", {}).get("7", {}).get("images", [])

                # Validate that at least one image was saved
                if not images:
                    raise RuntimeError("Workflow completed without a saved image")

                # Print the absolute path for each saved image
                # The image dict contains "filename" and optionally "subfolder"
                for image in images:
                    path = OUTPUT_ROOT / image.get("subfolder", "") / image["filename"]
                    print(path.resolve())
                return

        # Wait 1 second before polling again to avoid hammering the server
        time.sleep(1)

    # If we exit the loop without returning, the workflow timed out
    raise TimeoutError(f"ComfyUI workflow {prompt_id} did not finish within 300 seconds")


if __name__ == "__main__":
    main()
