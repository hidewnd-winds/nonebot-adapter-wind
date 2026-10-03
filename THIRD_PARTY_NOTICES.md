# 第三方许可说明

运行时依赖由安装工具从各上游发行包安装，协议扩展保留来源工程的上游适配器覆写逻辑，并继续通过依赖调用 SDK。以下适配器 SDK 按自身许可单独分发：

| 依赖 | 版本基线 | 许可 | 上游 |
|---|---:|---|---|
| NoneBot QQ Adapter | 1.7.3 | MIT | [nonebot/adapter-qq](https://github.com/nonebot/adapter-qq) |
| NoneBot OneBot Adapter | 2.4.6 | MIT | [nonebot/adapter-onebot](https://github.com/nonebot/adapter-onebot) |
| NoneBot2 | 2.5.x | 以其发行包元数据和上游仓库为准 | [nonebot/nonebot2](https://github.com/nonebot/nonebot2) |

QQ Adapter 1.7.3 的本地发行元数据声明 `MIT`；OneBot Adapter 2.4.6 发行包包含 MIT 许可文本，其版权声明为 NoneBot 2021。为保留 OneBot 反向连接扩展中相关上游声明，附录同时保留发行包的完整 MIT 文本。未来新增直接复制内容时仍须更新来源和许可记录。

依赖树中的其他库及可选 COS SDK 由其各自发行包携带许可。发布时应随发行清单核查最终解析版本及许可，不应把本项目的 MIT 声明视为第三方代码授权的替代。

## OneBot Adapter 2.4.6 许可原文

```text
MIT License

Copyright (c) 2021 NoneBot

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
