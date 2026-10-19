# 干净 Windows Sandbox 安装/EXE 验收（r26/r27/r28/r29）

日期：2026-10-20。当前候选：`E:/SumikaBuild/acceptance-20261017-current/candidate-rc2-r29`。

## r29 复验

- 归档 SHA256：`29b73697e39d5641fe1e9300f5ae35b4b2886111ce4a1a870624c11d0155fd18`
- 安装 + 库存 + EXE 生命周期四组通过：`passed:true`
- 报告：`E:/SumikaBuild/clean-windows-r29-20261020/results/report.json`
- 隔离归档/`install_sumika.ps1`/EXE 复验：`E:/SumikaBuild/acceptance-20261017-current/packaged-install-3d14b410edc14345b36f01a54efbeb49/report.json`，`passed:true`

## r28 复验

- 归档 SHA256：`c44e14d906b2de8a1ae57128af4d3f28ed231cb8d124c6d5b601c09142ebd8c5`
- 安装 + 库存 + EXE 生命周期四组通过：`passed:true`
- 报告：`E:/SumikaBuild/clean-windows-r28-20261019/results/report.json`
- 该包包含 B 站 seek 音频保活与登录态 CC DOM 字幕读取。

## r27 复验

- 归档 SHA256：`1a0a6bdb19b08617e9516e61a4274030281a418b53fdb0e1bc447044de5a108b`
- 安装 + 库存 + EXE 生命周期四组通过：`passed:true`
- 报告：`E:/SumikaBuild/clean-windows-r27-20261019/results/report.json`
- 该包包含 B 站 seek 后音频保活修复。

## 历史 r26

## 结果

- 沙箱：Windows Sandbox，`Microsoft Windows NT 10.0.26100.0`，隔离用户 `WDAGUtilityAccount`
- 归档 SHA256：`067ffbf1a613cb9278ae666cb7ef66748b41c94e2b504b28c9de891ca6cc9f28`
- 安装脚本 + 库存校验 + 实际 EXE 生命周期：**通过**
  - 首次启动
  - 复用
  - 外来 HTTP 200 拒绝并保留
  - 认证关闭与进程退出
- 报告：`E:/SumikaBuild/clean-windows-r26-20261019-root2/results/report.json`
- 安装后工作目录：沙箱内 `C:\Users\WDAGUtilityAccount\AppData\Local\SumikaAcceptance-...`；未触碰宿主日用数据。

## 发现并修复

前两次 Sandbox 均在 `install` 阶段失败：

```text
Archive contains a non-release root
```

根因：`packaging/install_sumika.ps1` 的 release root 允许列表没有 `browser-extensions`，而 r26 归档包含生产 companion 扩展目录。已把 `browser-extensions` 加入允许列表，重建 Sandbox 包后通过。新增源码回归测试防止再次遗漏。

## 边界

- 只证明干净 Windows 中的**安装/库存/EXE 生命周期**，不证明全部功能、真实设备、真实模型或安装器升级/回滚。
- Windows Sandbox 使用映射目录，不是真实新硬件；GPU/摄像头/麦克风不可用。
- 未安装到宿主、未替换日用、未发布。
