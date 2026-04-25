# nanobot 二开分支规范

本文档记录当前仓库的远端结构、分支职责，以及后续同步官方更新与推送自己改动的推荐流程。

## 当前远端

本仓库当前使用两套远端：

- `origin`: 你的个人 GitHub fork
- `upstream`: 官方仓库 `HKUDS/nanobot`

可以用下面命令查看：

```bash
git remote -v
```

## 当前分支职责

推荐按下面方式理解和使用分支：

- `main`
  - 本地保留
  - 不用于日常开发
  - 主要作为参考基线

- `marin/custom-wire-api-responses`
  - 当前长期维护分支
  - 已包含本地补丁：
    - `custom.wireApi = "responses"`
    - yls 接入相关修改
    - 对应说明文档
  - 后续日常开发可以直接在这个分支继续

## 日常开发建议

如果改动还不大，可以直接在长期分支上继续开发：

```bash
git switch marin/custom-wire-api-responses
```

如果后续功能变多，推荐从长期分支再切新的功能分支：

```bash
git switch marin/custom-wire-api-responses
git switch -c feature/your-feature-name
```

做完后再合回长期分支。

## 同步官方更新

推荐流程：

```bash
git fetch upstream
git switch marin/custom-wire-api-responses
git merge upstream/main
```

这 3 步的含义分别是：

1. 从官方仓库拉取最新信息
2. 切回你自己的长期开发分支
3. 把官方 `main` 合并到你的分支

## 推送自己的改动

当前长期分支已经和你的远端分支建立跟踪关系，因此通常直接：

```bash
git push
```

如果是第一次推送一个新分支，可以用：

```bash
git push -u origin <branch-name>
```

## 推荐的最小工作流

### 继续在长期分支开发

```bash
git switch marin/custom-wire-api-responses
git status
git add <files>
git commit -m "your message"
git push
```

### 先同步官方，再继续开发

```bash
git fetch upstream
git switch marin/custom-wire-api-responses
git merge upstream/main
git push
```

## 关于 `main`

本地 `main` 可以保留，但不是必须参与日常流程。

也就是说，后续同步官方更新时，不必一定先：

```bash
git switch main
git pull
```

在当前这套结构下，直接：

```bash
git fetch upstream
git merge upstream/main
```

通常更直接，也更不容易混淆。

## 不推荐的做法

- 不要把官方仓库继续当成 `origin`
- 不要在 `main` 上直接做业务二开
- 不要长期只靠未提交的工作区改动维护功能
- 不要把本机运行配置文件当作源码仓库内容提交

## 当前已知事实

- 当前长期分支：`marin/custom-wire-api-responses`
- 当前补丁提交：`0e94f4a feat: support responses wire api for custom providers`
- 运行配置仍在本机：
  - `~/.nanobot/config.json`
- yls 接入说明文档：
  - [yls-responses-integration.md](/Users/marin/code/nanobot/docs/yls-responses-integration.md:1)

## 一句话版本

以后默认这样做就行：

```bash
git fetch upstream
git switch marin/custom-wire-api-responses
git merge upstream/main
git push
```
