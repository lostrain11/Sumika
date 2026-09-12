# 备份与恢复

阶段 0 使用 Git 保存项目记录、源码、发行描述与锁文件 checkpoint。提交前运行 `python -B -m sumika_next.cli check` 和相称测试，提交后记录 commit SHA。执行记录中的 SHA 指最近已存在的提交，不能在提交前编造本次 SHA。

项目运行数据的完整备份恢复列入 P7，首版暂不考虑加密。聊天、角色配置等私密运行数据保存在用户本地，不随源码上传；凭据使用运行时的安全存储，不写入 Git、验收报告或需求原文。原话含密钥时先脱敏并明确标记，不能伪称脱敏文本是完整逐字原文。

源码/记录恢复：在被忽略的 `.sumika-next/backups` 目录用 `git bundle create <目标.bundle> codex/sumika-next-dsh` 建恢复包，随后 `git bundle verify <目标.bundle>`。恢复到新的不存在目录：`git clone <目标.bundle> <新目录>`；依照固定锁重新安装，运行连续性校验。恢复通过前不替换当前项目。

运行数据后续恢复也先复制到隔离目录核对，不直接覆盖现有 profile；不能把 Git bundle 当作未跟踪运行数据备份。

新版分支不删除旧分支。需要回退时使用旧分支提交或独立恢复目录，不覆盖未提交数据。
