# [pioneer] vision2model

## 一句话
图像→3D 测量管线：输入带方格纸参照物的照片，输出结构化尺寸数据（JSON）+ SVG 验证图，可选生成 FreeCAD 建模脚本。

## 部署
```bash
pip install opencv-python scikit-image scipy scikit-learn pytest
python -m vision2model.image2model photo.jpg --grid-mm 5.0
```

## 依赖
- opencv-python (>=4.x)
- scikit-image (>=0.26)
- scipy (>=1.18)
- scikit-learn (>=1.9)
- numpy (>=2.4)
- pytest (测试用)

## 状态
✅ 交付 (P0-P4, 59/59 tests)

## 归属
Pioneer
