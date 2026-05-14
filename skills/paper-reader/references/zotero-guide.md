# Zotero 集成指南

## 查询分类下的论文（支持递归子分类）

```bash
# 使用辅助脚本
python3 assets/zotero_helper.py collections         # 列出所有分类
python3 assets/zotero_helper.py papers 1            # 列出分类ID=1的论文
python3 assets/zotero_helper.py papers 1 --recursive # 递归包含子分类
python3 assets/zotero_helper.py pdf 12345           # 获取论文PDF路径
python3 assets/zotero_helper.py resolve --query "EBPC" --limit 10
python3 assets/zotero_helper.py resolve --item-id 2487
python3 assets/zotero_helper.py resolve --collection "Link & Fabric Integration" --recursive
```

**递归查询原理**：
1. 先获取目标分类的所有子分类 ID（递归遍历 parentCollectionID）
2. 用 `WHERE ci.collectionID IN (id1, id2, ...)` 查询所有论文
3. 去重（同一论文可能在多个分类中）

## 获取论文 PDF 路径

```sql
SELECT ia.path, items.key
FROM itemAttachments ia
JOIN items ON ia.itemID = items.itemID
WHERE ia.parentItemID = {item_id} AND ia.contentType = 'application/pdf';
-- 完整路径: {ZOTERO_STORAGE}/{key}/{filename}
```

## 获取 Zotero 分类路径

```python
def get_collection_path(collection_id):
    """返回完整路径如 '4-Distributed Systems/Serving'"""
    cursor.execute("SELECT collectionID, collectionName, parentCollectionID FROM collections")
    collections = {row[0]: {'name': row[1], 'parent': row[2]} for row in cursor.fetchall()}
    path_parts = []
    current = collection_id
    while current:
        if current in collections:
            path_parts.insert(0, collections[current]['name'])
            current = collections[current]['parent']
        else:
            break
    return '/'.join(path_parts)
```

## 结构化解析与保存路径

`resolve` 命令输出 JSON，包含：

- `item_id`、`title`、`authors`、`year`、`venue`
- `url`、`doi`、`arxiv_id`、`pdf_path`
- `collection_paths`: item 所在全部 collection 完整路径
- `source_collection_path`: 批量递归 collection 时，item 在该 subtree 下最具体的来源 collection

Obsidian 保存路径使用 `{NOTES_PATH}/{selected_collection_path}/{MethodName}.md`。没有 collection 的 item 保存到 `{NOTES_PATH}/_inbox/{MethodName}.md`。

```bash
python3 assets/zotero_helper.py note-path EBPC \
  --collection-path "Research Topics/Lossless Communication Compression/Link & Fabric Integration" \
  --zotero-item-id 2487
```

## 分类判断

Zotero 默认只读。阅读时不要按关键词自动改 Zotero 分类；如果分类明显不对，只给出建议和理由，等用户确认后再执行修改命令。

## Zotero 分类操作

⚠️ 以下命令会修改 Zotero 数据库。默认不要主动调用；先在笔记或回复里写出分类调整建议和理由，只有用户明确确认执行后才调用：

```bash
# 查看论文当前分类
python3 assets/zotero_helper.py info {item_id}
# 查找目标分类 ID
python3 assets/zotero_helper.py find-collection "Distributed Systems"
# 移动论文
python3 assets/zotero_helper.py move {item_id} {new_collection_id} --from {old_collection_id}
# 添加到多个分类
python3 assets/zotero_helper.py add-to-collection {item_id} {collection_id}
# 从分类移除
python3 assets/zotero_helper.py remove-from-collection {item_id} {collection_id}
```
