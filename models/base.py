from pathlib import Path

import peft
import torch
from torch import nn
import safetensors.torch
import torchvision
from PIL import ImageOps
from torchvision import transforms
import imageio

from utils.common import is_main_process, VIDEO_EXTENSIONS


def extract_clips(video, target_frames, video_clip_mode):
    # video is (channels, num_frames, height, width)
    frames = video.shape[1]
    if frames < target_frames:
        # TODO: think about how to handle this case. Maybe the video should have already been thrown out?
        print(f'video with shape {video.shape} is being skipped because it has less than the target_frames')
        return []

    if video_clip_mode == 'single_beginning':
        return [video[:, :target_frames, ...]]
    elif video_clip_mode == 'single_middle':
        start = int((frames - target_frames) / 2)
        assert frames-start >= target_frames
        return [video[:, start:start+target_frames, ...]]
    elif video_clip_mode == 'multiple_overlapping':
        # Extract multiple clips so we use the whole video for training.
        # The clips might overlap a little bit. We never cut anything off the end of the video.
        num_clips = ((frames - 1) // target_frames) + 1
        start_indices = torch.linspace(0, frames-target_frames, num_clips).int()
        return [video[:, i:i+target_frames, ...] for i in start_indices]
    else:
        raise NotImplementedError(f'video_clip_mode={video_clip_mode} is not recognized')


class PreprocessMediaFile:
    def __init__(self, config, support_video=False, framerate=None):
        self.config = config
        self.video_clip_mode = config.get('video_clip_mode', 'single_middle')
        print(f'using video_clip_mode={self.video_clip_mode}')
        self.pil_to_tensor = transforms.Compose([transforms.ToTensor(), transforms.Normalize([0.5], [0.5])])
        self.support_video = support_video
        self.framerate = framerate
        if self.support_video:
            assert self.framerate

    def __call__(self, filepath, size_bucket):
        width, height, frames = size_bucket
        height_padded = ((height - 1) // 32 + 1) * 32
        width_padded = ((width - 1) // 32 + 1) * 32
        frames_padded = ((frames - 2) // 8 + 1) * 8 + 1

        is_video = (Path(filepath).suffix in VIDEO_EXTENSIONS)
        if is_video:
            assert self.support_video
            num_frames = 0
            for frame in imageio.v3.imiter(filepath, fps=self.framerate):
                channels = frame.shape[-1]
                num_frames += 1
            frames = imageio.v3.imiter(filepath, fps=self.framerate)
        else:
            num_frames = 1
            frames = [imageio.v3.imread(filepath)]
            channels = frames[0].shape[-1]

        video = torch.empty((num_frames, channels, height_padded, width_padded))
        for i, frame in enumerate(frames):
            pil_image = torchvision.transforms.functional.to_pil_image(frame)
            cropped_image = ImageOps.fit(pil_image, (width_padded, height_padded))
            video[i, ...] = self.pil_to_tensor(cropped_image)

        if not self.support_video:
            return [video.squeeze(0)]

        # (num_frames, channels, height, width) -> (channels, num_frames, height, width)
        video = torch.permute(video, (1, 0, 2, 3))
        if not is_video:
            return [video]
        else:
            return extract_clips(video, frames_padded, self.video_clip_mode)


class BasePipeline:
    def get_vae(self):
        raise NotImplementedError()

    def get_text_encoders(self):
        raise NotImplementedError()

    def configure_adapter(self, adapter_config):
        target_linear_modules = []
        for module in self.transformer.modules():
            if module.__class__.__name__ not in self.adapter_target_modules:
                continue
            for name, submodule in module.named_modules():
                if isinstance(submodule, nn.Linear):
                    target_linear_modules.append(name)

        adapter_type = adapter_config['type']
        if adapter_type == 'lora':
            peft_config = peft.LoraConfig(
                r=adapter_config['rank'],
                lora_alpha=adapter_config['alpha'],
                lora_dropout=adapter_config['dropout'],
                bias='none',
                target_modules=target_linear_modules
            )
        else:
            raise NotImplementedError(f'Adapter type {adapter_type} is not implemented')
        self.peft_config = peft_config
        self.lora_model = peft.get_peft_model(self.transformer, peft_config)
        #self.transformer.add_adapter(peft_config)
        if is_main_process():
            self.lora_model.print_trainable_parameters()
        for name, p in self.transformer.named_parameters():
            p.original_name = name
            if p.requires_grad:
                p.data = p.data.to(adapter_config['dtype'])
        return peft_config

    def save_adapter(self, save_dir, peft_state_dict):
        raise NotImplementedError()

    def load_adapter_weights(self, adapter_path):
        if is_main_process():
            print(f'Loading adapter weights from path {adapter_path}')
        adapter_state_dict = safetensors.torch.load_file(Path(adapter_path) / 'adapter_model.safetensors')
        modified_state_dict = {}
        model_parameters = set(name for name, p in self.transformer.named_parameters())
        for k, v in adapter_state_dict.items():
            k = k.replace('transformer.', '')
            k = k.replace('weight', 'default.weight')
            if k not in model_parameters:
                raise RuntimeError(f'modified_state_dict key {k} is not in the model parameters')
            modified_state_dict[k] = v
        self.transformer.load_state_dict(modified_state_dict, strict=False)

    def save_model(self, save_dir, diffusers_sd):
        raise NotImplementedError()

    def get_latents_map_fn(self, vae, size_bucket):
        raise NotImplementedError()

    def get_text_embeddings_map_fn(self, text_encoder):
        raise NotImplementedError()

    def prepare_inputs(self, inputs, timestep_quantile=None):
        raise NotImplementedError()

    def to_layers(self):
        raise NotImplementedError()
