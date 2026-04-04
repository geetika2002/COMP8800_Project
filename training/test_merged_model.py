from transformers import AutoTokenizer, AutoModelForCausalLM

model_path = "ft/outputs/tinyllama-merged"

tokenizer = AutoTokenizer.from_pretrained(model_path, use_fast=False)
model = AutoModelForCausalLM.from_pretrained(model_path)

prompt = "<|system|>\nYou are a helpful assistant.\n<|user|>\nhello\n<|assistant|>\n"

inputs = tokenizer(prompt, return_tensors="pt")
outputs = model.generate(
    **inputs,
    max_new_tokens=80,
    do_sample=False
)

text = tokenizer.decode(outputs[0], skip_special_tokens=False)
print(text)
