import io

with io.open('main.js', 'rb') as f:
    js = f.read()

# 1. 加 import
old_import = b"import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';"
new_import = old_import + b"\nimport { DRACOLoader } from 'three/addons/loaders/DRACOLoader.js';"

if b'DRACOLoader' not in js:
    js = js.replace(old_import, new_import)
    print('import added')

# 2. 找到 loader 创建位置，配置 DRACOLoader
old_loader = b"const loader = new GLTFLoader();"
new_loader = b'''const draco = new DRACOLoader();
  draco.setDecoderPath('https://www.gstatic.com/draco/versioned/decoders/1.5.6/');
  const loader = new GLTFLoader();
  loader.setDRACOLoader(draco);'''

if b'setDRACOLoader' not in js:
    js = js.replace(old_loader, new_loader)
    print('DRACOLoader config added')

with io.open('main.js', 'wb') as f:
    f.write(js)
