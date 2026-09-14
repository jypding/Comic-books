import io, json

path = r"D:\GitRepos\Comic-books\projects\第 2页\s01e01\manifest.json"

with io.open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

data["mode"] = "cinematic"

with io.open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("已加 mode: cinematic")
print(json.dumps(data, ensure_ascii=False, indent=2))
