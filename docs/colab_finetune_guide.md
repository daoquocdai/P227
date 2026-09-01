# HƯỚNG DẪN FINETUNE QWEN2.5-0.5B TRÊN GOOGLE COLAB CHO GUARDIANCAM

## BƯỚC 1: Cấu hình GPU trên Google Colab
1. Vào menu **Runtime (Thời gian chạy)** -> **Change runtime type (Thay đổi loại thời gian chạy)**.
2. Chọn **T4 GPU** -> Bấm **Save**.

---

## BƯỚC 2: Upload tập Dataset
1. Bấm vào biểu tượng **Thư mục 📁** ở thanh công cụ bên trái Colab.
2. Kéo và thả file `dataset_guardiancam_1200.jsonl` (tại đường dẫn `d:\LABVin\P-227\data\tracinghuman\dataset_guardiancam_1200.jsonl`) vào Colab.

---

## BƯỚC 3: Chạy các Cell Code huấn luyện

### Cell 1: Cài đặt thư viện Unsloth
```bash
!pip install unsloth unsloth_zoo datasets trl peft bitsandbytes huggingface_hub
```

### Cell 2: Tiến hành Huấn luyện (Fine-tuning)
```python
from unsloth import FastLanguageModel
import torch
from datasets import load_dataset
from trl import SFTTrainer
from transformers import TrainingArguments

max_seq_length = 2048

# 1. Load Base Model Qwen2.5-0.5B-Instruct
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = "Qwen/Qwen2.5-0.5B-Instruct",
    max_seq_length = max_seq_length,
    dtype = None,
    load_in_4bit = True,
)

# 2. Thêm LoRA Adapters
model = FastLanguageModel.get_peft_model(
    model,
    r = 16,
    target_modules = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    lora_alpha = 16,
    lora_dropout = 0,
    bias = "none",
    use_gradient_checkpointing = "unsloth",
    random_state = 3407,
)

# 3. Format Prompt ChatML & Load Dataset
def format_prompts(examples):
    texts = []
    for messages in examples["messages"]:
        text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
        texts.append(text)
    return {"text": texts}

dataset = load_dataset("json", data_files="dataset_guardiancam_1200.jsonl", split="train")
dataset = dataset.map(format_prompts, batched=True)

# 4. SFT Trainer (Huấn luyện trong ~5-8 phút)
trainer = SFTTrainer(
    model = model,
    tokenizer = tokenizer,
    train_dataset = dataset,
    dataset_text_field = "text",
    max_seq_length = max_seq_length,
    dataset_num_proc = 2,
    packing = False,
    args = TrainingArguments(
        per_device_train_batch_size = 4,
        gradient_accumulation_steps = 4,
        warmup_steps = 10,
        max_steps = 120,
        learning_rate = 2e-4,
        fp16 = not torch.cuda.is_bf16_supported(),
        bf16 = torch.cuda.is_bf16_supported(),
        logging_steps = 10,
        optim = "adamw_8bit",
        weight_decay = 0.01,
        lr_scheduler_type = "linear",
        seed = 3407,
        output_dir = "outputs",
    ),
)

trainer_stats = trainer.train()
print("🎉 ĐÃ HUẤN LUYỆN XONG!")
```

### Cell 3: Xuất mô hình thành file GGUF
```python
model.save_pretrained_gguf("qwen2.5-0.5b-guardiancam", tokenizer, quantization_method = "q4_k_m")
print("✅ Xuất mô hình GGUF thành công!")
```

---

## BƯỚC 4: Tải file .gguf về máy & Import vào Ollama

1. Tại tab Thư mục bên trái Colab 📁, mở thư mục `qwen2.5-0.5b-guardiancam`.
2. Chuột phải vào file `qwen2.5-0.5b-guardiancam-Q4_K_M.gguf` -> Chọn **Download** (Dung lượng ~350MB).
3. Đặt file vào thư mục dự án `d:\LABVin\P-227\models\`.
4. Mở PowerShell tại dự án và chạy:
   ```bash
   ollama create qwen2.5-0.5b-guardiancam -f Modelfile
   ```
