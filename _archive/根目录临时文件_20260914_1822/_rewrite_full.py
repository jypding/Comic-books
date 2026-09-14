import io

path = r"D:\GitRepos\Comic-books\.github\workflows\pages.yml"

with io.open(path, "r", encoding="utf-8") as f:
    old = f.read()
with io.open(path + ".bak_full", "w", encoding="utf-8") as f:
    f.write(old)
print("已备份: pages.yml.bak_full")

new_content = """name: Deploy GitHub Pages
on:
  push:
    branches: [ main ]

permissions:
  contents: write

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout (with LFS)
        uses: actions/checkout@v4
        with:
          lfs: true

      - name: Ensure Git LFS installed and objects pulled
        run: |
          git lfs install --local
          git lfs pull
          git lfs checkout
          echo "=== LFS status ==="
          git lfs ls-files | head -50

      - name: Setup Node
        uses: actions/setup-node@v4
        with:
          node-version: 24
          cache: 'npm'
          cache-dependency-path: viewer-needle/package-lock.json

      - name: Install & Build
        working-directory: ./viewer-needle
        run: |
          npm ci
          npm run build

      - name: Verify all .glb files are real binary (not LFS pointer)
        run: |
          FAIL=0
          for f in $(find books -name "*.glb" -type f); do
            SIZE=$(stat -c%s "$f")
            HEAD=$(head -c 40 "$f" || true)
            if echo "$HEAD" | grep -q "version https://git-lfs"; then
              echo "FAIL: $f is LFS pointer (size=$SIZE)"
              FAIL=1
            elif [ "$SIZE" -lt 200 ]; then
              echo "FAIL: $f too small ($SIZE bytes)"
              FAIL=1
            else
              echo "OK: $f (size=$SIZE)"
            fi
          done
          if [ "$FAIL" = "1" ]; then
            echo "=== At least one .glb is still an LFS pointer. Aborting. ==="
            exit 1
          fi
          echo "=== All .glb files are real binary ==="

      - name: Copy books to dist
        run: |
          mkdir -p ./viewer-needle/dist/books
          cp -r ./books/. ./viewer-needle/dist/books/
          # 删除 LFS 相关配置，避免 gh-pages 继承
          find ./viewer-needle/dist -name ".gitattributes" -type f -delete
          echo "=== Verify GLB in dist ==="
          stat -c%s ./viewer-needle/dist/books/mmdd111/book/pages/joshu_dog_sample/scene.glb

      - name: Deploy Pages
        uses: peaceiris/actions-gh-pages@v4
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: ./viewer-needle/dist
          enable_jekyll: false
          force_orphan: true
"""

with io.open(path, "w", encoding="utf-8") as f:
    f.write(new_content)
print("已重写 pages.yml")
