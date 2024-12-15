# diffusion-pipe
A pipeline parallel training script for diffusion models.

Currently supports Flux, LTX-Video, and HunyuanVideo.

**Work in progress and highly experimental.** It is unstable and not well tested. Things might not work right.

## Features
- Pipeline parallelism, for training models larger than can fit on a single GPU
- Full fine tune support for:
    - Flux
- LoRA support for:
    - Flux, LTX-Video, HunyuanVideo
- Useful metrics logged to Tensorboard
- Compute metrics on a held-out eval set, for measuring generalization
- Training state checkpointing and resuming from checkpoint
- Efficient multi-process, multi-GPU pre-caching of latents and text embeddings
- Easily add support for new models by implementing a single subclass


## Windows support
There are reports that it doesn't work on Windows. This is because Deepspeed only has [partial Windows support](https://github.com/microsoft/DeepSpeed/blob/master/blogs/windows/08-2024/README.md). However, at least one user was able to get it running and training successfully on Windows Subsystem for Linux, specifically WSL 2. If you must use Windows I recommend trying WSL 2.


## Installing
Clone the repository:
```bash
sudo apt-get update && sudo apt-get install git-lfs ffmpeg cbm
```

```
git clone --recurse-submodules https://github.com/svjack/diffusion-pipe
```

If you alread cloned it and forgot to do --recurse-submodules:
```
git submodule init
git submodule update
```

Install Miniconda: https://docs.anaconda.com/miniconda/

Create the environment:
```
conda create -n diffusion-pipe python=3.12
conda activate diffusion-pipe
pip install ipykernel
python -m ipykernel install --user --name diffusion-pipe --display-name "diffusion-pipe"
```

Install nvcc: https://anaconda.org/nvidia/cuda-nvcc. Probably try to make it match the CUDA version that was installed on your system with PyTorch.

Install the dependencies:
```
pip install -r requirements.txt
pip install flash-attn
```

## Download models 
```bash
git clone https://huggingface.co/Kijai/HunyuanVideo_comfy
git clone https://huggingface.co/Kijai/llava-llama-3-8b-text-encoder-tokenizer
git clone https://huggingface.co/openai/clip-vit-large-patch14
```

## Download dataset 
- Genshin Impact Landscape
```bash
#### 不能使用太短的视频
huggingface-cli download \
  --repo-type dataset svjack/video-dataset-genshin-impact-ep-landscape-organized \
  --local-dir video-dataset-genshin-impact-ep-landscape-organized

mkdir Genshin-Impact-Landscape
cp video-dataset-genshin-impact-ep-landscape-organized/*.mp4 Genshin-Impact-Landscape
cp video-dataset-genshin-impact-ep-landscape-organized/*.txt Genshin-Impact-Landscape
```

- Genshin Impact Character Xiangling
```bash
#### 不能使用太短的视频
huggingface-cli download \
  --repo-type dataset svjack/Genshin-Impact-XiangLing-animatediff-with-score-organized \
  --local-dir Genshin-Impact-XiangLing-animatediff-with-score-organized

mkdir Genshin-Impact-XiangLing
cp Genshin-Impact-XiangLing-animatediff-with-score-organized/*.mp4 Genshin-Impact-XiangLing
cp Genshin-Impact-XiangLing-animatediff-with-score-organized/*.txt Genshin-Impact-XiangLing
```
```python
!pip install moviepy==1.0.3
import os
import shutil
from moviepy.editor import VideoFileClip
from tqdm import tqdm

def process_videos(input_folder, output_folder, target_duration=60):
    """
    处理输入文件夹中的视频文件，循环视频以达到目标时长，并将结果保存到输出文件夹。
    同时直接拷贝其他非视频文件。

    参数:
    input_folder (str): 输入文件夹路径
    output_folder (str): 输出文件夹路径
    target_duration (int): 目标视频时长（秒），默认为60秒
    """
    # 创建输出文件夹
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    # 获取输入文件夹中的所有文件
    files = os.listdir(input_folder)

    for file in tqdm(files, desc="Processing files"):
        input_path = os.path.join(input_folder, file)
        output_path = os.path.join(output_folder, file)

        # 检查文件是否为视频文件（简单判断扩展名）
        if file.lower().endswith(('.mp4', '.avi', '.mov', '.mkv')):
            # 打开视频文件
            clip = VideoFileClip(input_path)

            # 计算需要循环的次数
            loop_count = int(target_duration // clip.duration) + 1

            # 循环视频
            looped_clip = clip.loop(loop_count)

            # 裁剪到目标时长
            looped_clip = looped_clip.subclip(0, target_duration)

            # 保存循环后的视频
            looped_clip.write_videofile(output_path, codec='libx264')

            # 关闭视频文件
            clip.close()
            looped_clip.close()
        else:
            # 直接拷贝非视频文件
            shutil.copy(input_path, output_path)

    print("处理完成！")

# 示例调用
input_folder = "Genshin-Impact-XiangLing"
output_folder = "Genshin-Impact-XiangLing-Long"
process_videos(input_folder, output_folder, 6)
```
- Tune result (Epoch 4 seed 42 prompt: solo,Xiangling, cook rice in a pot genshin impact ,1girl,highres,)
- Inference in https://github.com/svjack/ComfyUI-HunyuanVideoWrapper


https://github.com/user-attachments/assets/e3bce8ba-cb37-4c7b-a1fc-973cb6dc4cfb


## Training
**Start by reading through the config files in the examples directory.** Almost everything is commented, explaining what each setting does.

Once you've familiarized yourself with the config file format, go ahead and make a copy and edit to your liking. At minimum, change all the paths to conform to your setup, including the paths in the dataset config file.

Launch training like this:
```
NCCL_P2P_DISABLE="1" NCCL_IB_DISABLE="1" deepspeed --num_gpus=1 train.py --deepspeed --config examples/hunyuan_video.toml
```
RTX 4000 series needs those 2 environment variables set. Other GPUs may not need them. You can try without them, Deepspeed will complain if it's wrong.

If you enabled checkpointing, you can resume training from the latest checkpoint by simply re-running the exact same command but with the ```--resume_from_checkpoint``` flag.

## VRAM requirements
### Flux
Flux doesn't currently support training a LoRA on a fp8 base model (if you want this, PRs are welcome :) ). So you need to use a >24GB GPU, or use pipeline_stages=2 or higher with multiple 24GB cards. With four 24GB GPUs, you can even full finetune Flux with the right techniques (see the train.py code about gradient release and the custom AdamW8bitKahan optimizer).

### HunyuanVideo
HunyuanVideo supports fp8 transformer. The example config file will train a HunyuanVideo LoRA, on images only, in well under 24GB of VRAM. You can probably bump the resolution to 1024x1024 or higher.

Video uses A LOT more memory. I was able to train a rank 32 LoRA on 512x512x33 sized videos in just under 23GB VRAM usage. Pipeline parallelism will help a bit if you have multiple GPUs, since the model weights will be further divided among them (but it doesn't help with the huge activation memory use of videos). Long term I want to eventually implement ring attention and/or Deepspeed Ulysses for parallelizing the sequence dimension across GPUs, which should greatly help for training on videos.

### LTX-Video
I've barely done any training on LTX-Video. The model is much lighter than Hunyuan, and the latent space more compressed, so it uses less memory. You can train loras even on video at a reasonable length (I forgot exactly what it was) on 24GB.

## Parallelism
This code uses hybrid data- and pipeline-parallelism. Set the ```--num_gpus``` flag appropriately for your setup. Set ```pipeline_stages``` in the config file to control the degree of pipeline parallelism. Then the data parallelism degree will automatically be set to use all GPUs (number of GPUs must be divisible by pipeline_stages). For example, with 4 GPUs and pipeline_stages=2, you will run two instances of the model, each divided across two GPUs. Note that due to a weird bug I'm still investigating, pipeline_stages>1 doesn't work with HunyuanVideo.

## Pre-caching
Latents and text embeddings are cached to disk before training happens. This way, the VAE and text encoders don't need to be kept loaded during training. The Huggingface Datasets library is used for all the caching. Cache files are reused between training runs if they exist. All cache files are written into a directory named "cache" inside each dataset directory.

This caching also means that training LoRAs for text encoders is not currently supported.

Two flags are relevant for caching. ```--cache_only``` does the caching flow, then exits without training anything. ```--regenerate_cache``` forces cache regeneration. If you edit the dataset in-place (like changing a caption), you need to force regenerate the cache (or delete the cache dir) for the changes to be picked up.

## HunyuanVideo LoRAs
HunyuanVideo doesn't have an official Diffusers integration yet, and as such it doesn't have an official LoRA format. This script currently outputs the LoRA in a format that directly works with ComfyUI. Make sure the HunyuanVideoWrapper extension is fully updated, and use the "HunyuanVideo Lora Select" node.

## Extra
You can check out my [qlora-pipe](https://github.com/tdrussell/qlora-pipe) project, which is basically the same thing as this but for LLMs.
