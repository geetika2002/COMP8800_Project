from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

base_model = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"
lora_path = "ft/outputs/tinyllama-lora-v2"
output_path = "ft/outputs/tinyllama-merged"

print("Loading base model...")
model = AutoModelForCausalLM.from_pretrained(
    base_model,
    torch_dtype="auto",
    device_map="cpu"
)

print("Loading tokenizer...")
tokenizer = AutoTokenizer.from_pretrained(base_model, use_fast=False)

print("Loading LoRA adapter...")
model = PeftModel.from_pretrained(model, lora_path)

print("Merging LoRA...")
model = model.merge_and_unload()

print("Saving merged model...")
model.save_pretrained(output_path)
tokenizer.save_pretrained(output_path)

print("Done!")