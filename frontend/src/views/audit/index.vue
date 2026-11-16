<template>
  <section class="page" data-module="audit">
    <header class="page-head">
      <div>
        <h2>日志审计数据集</h2>
        <p class="page-desc">
          按采集请求日志批次建立审计数据集，主链只追加、相同记录只写一次；摘要断点进入审计交付待处理队列，导出批次按同一归档顺序逐条给出摘要。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">建立审计数据集</button>
        <button class="btn" type="button" :disabled="!current" @click="runRecheck">复测摘要链</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>数据集编号 / 归档文件</span>
        <input v-model="filters.keyword" placeholder="按数据集编号或归档文件检索" />
      </label>
      <label class="filter-item">
        <span>状态</span>
        <select v-model="filters.status">
          <option value="">全部</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in rows"
          :key="String(row.id)"
          :class="{ 'row-active': current && current.id === row.id }"
          @click="select(row)"
        >
          <td v-for="column in columns" :key="column">{{ display(row[column]) }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click.stop="select(row)">查看节点</button>
            <button class="link" type="button" @click.stop="runAction('校验摘要链', row)">校验摘要链</button>
            <button
              class="link"
              type="button"
              :disabled="row.status === '已封存'"
              @click.stop="runAction('封存数据集', row)"
            >
              封存数据集
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无日志审计数据集，可先按批次建立</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 个日志审计数据集</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <template v-if="current">
      <section class="detail-panel">
        <header class="detail-head">
          <div>
            <h3>{{ current.数据集编号 }} · {{ current.归档文件 }}</h3>
            <p class="page-desc">
              来源批次 {{ current.来源批次 }} · 采集请求 {{ current.采集请求数 }} 条 ·
              主节点 {{ current.主节点数 }} · 更正段 {{ current.更正段数 }} ·
              摘要断点 {{ current.摘要断点数 }}
            </p>
          </div>
          <div class="detail-meta">
            <span>首条时间 {{ current.首条时间 ?? '—' }}</span>
            <span>末条时间 {{ current.末条时间 ?? '—' }}</span>
            <span>尾链摘要 {{ current.尾链摘要 ?? '—' }}</span>
          </div>
        </header>

        <div class="stat-row">
          <article v-for="item in verifyChecks" :key="item.名称" class="stat-card check-card">
            <span class="stat-label">{{ item.名称 }}</span>
            <strong class="stat-value" :class="item.通过 ? 'ok-text' : 'error-text'">
              {{ item.通过 ? '通过' : '未通过' }}
            </strong>
            <span class="check-note">{{ item.说明 }}</span>
          </article>
        </div>

        <nav class="tab-bar">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            class="tab"
            type="button"
            :class="{ active: activeTab === tab.key }"
            @click="activeTab = tab.key"
          >
            {{ tab.label }}
          </button>
        </nav>

        <div v-if="activeTab === 'nodes'">
          <div class="filter-bar">
            <label class="filter-item">
              <span>只显示</span>
              <select v-model="nodeFilter">
                <option value="all">全部节点</option>
                <option value="main">主节点</option>
                <option value="correction">更正段</option>
                <option value="breakpoint">摘要断点</option>
              </select>
            </label>
          </div>
          <table class="data-table">
            <thead>
              <tr>
                <th>主链序号</th>
                <th>节点编号</th>
                <th>节点类型</th>
                <th>记录编号</th>
                <th>请求时间</th>
                <th>记录摘要</th>
                <th>前序摘要</th>
                <th>链摘要</th>
                <th>归属节点</th>
                <th>顺序</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="node in visibleNodes" :key="node.节点编号">
                <td>{{ node.主链序号 ?? '—' }}</td>
                <td>{{ node.节点编号 }}</td>
                <td>{{ node.节点类型 }}</td>
                <td>{{ node.记录编号 }}</td>
                <td>{{ node.请求时间 }}</td>
                <td>{{ node.记录摘要 }}</td>
                <td class="digest">{{ node.前序摘要 }}</td>
                <td class="digest">{{ node.链摘要 }}</td>
                <td>{{ node.归属节点 ?? '—' }}</td>
                <td :class="node.顺序异常 ? 'error-text' : ''">{{ node.顺序异常 ? '迟到追加' : '正常' }}</td>
              </tr>
              <tr v-if="!visibleNodes.length">
                <td colspan="10" class="empty-state">没有符合条件的节点</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-else-if="activeTab === 'export'">
          <div class="filter-bar">
            <button class="btn" type="button" @click="loadExport">读取导出详情</button>
            <button class="btn ghost" type="button" :disabled="!exportDetail" @click="downloadExport">
              下载导出文件
            </button>
            <span v-if="exportDetail" class="inline-note">
              导出批次 {{ exportDetail.导出批次 }} · 记录数 {{ exportDetail.记录数 }} ·
              首条时间 {{ exportDetail.首条时间 ?? '—' }} · 摘要断点 {{ exportDetail.摘要断点.length }}
            </span>
          </div>
          <table v-if="exportDetail" class="data-table">
            <thead>
              <tr>
                <th>序号</th>
                <th>节点编号</th>
                <th>记录编号</th>
                <th>请求时间</th>
                <th>记录摘要</th>
                <th>前序摘要</th>
                <th>链摘要</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in exportDetail.摘要顺序" :key="item.序号">
                <td>{{ item.序号 }}</td>
                <td>{{ item.节点编号 }}</td>
                <td>{{ item.记录编号 }}</td>
                <td>{{ item.请求时间 }}</td>
                <td>{{ item.记录摘要 }}</td>
                <td class="digest">{{ item.前序摘要 }}</td>
                <td class="digest">{{ item.链摘要 }}</td>
              </tr>
            </tbody>
          </table>
          <h4 v-if="exportDetail">摘要断点</h4>
          <table v-if="exportDetail" class="data-table">
            <thead>
              <tr>
                <th>断点节点</th>
                <th>节点类型</th>
                <th>记录编号</th>
                <th>记录摘要</th>
                <th>归属节点</th>
                <th>队列编号</th>
                <th>裁决编号</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in exportDetail.摘要断点" :key="item.断点节点">
                <td>{{ item.断点节点 }}</td>
                <td>{{ item.节点类型 }}</td>
                <td>{{ item.记录编号 }}</td>
                <td>{{ item.记录摘要 }}</td>
                <td>{{ item.归属节点 ?? '—' }}</td>
                <td>{{ item.队列编号 ?? '—' }}</td>
                <td>{{ item.裁决编号 ?? '—' }}</td>
              </tr>
              <tr v-if="!exportDetail.摘要断点.length">
                <td colspan="7" class="empty-state">该批次没有摘要断点</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-else-if="activeTab === 'conflicts'">
          <table class="data-table">
            <thead>
              <tr>
                <th>裁决编号</th>
                <th>冲突类型</th>
                <th>记录编号</th>
                <th>请求时间</th>
                <th>原节点</th>
                <th>节点编号</th>
                <th>状态</th>
                <th>冲突说明</th>
                <th>可执行动作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in current.conflicts" :key="item.裁决编号">
                <td>{{ item.裁决编号 }}</td>
                <td>{{ item.冲突类型 }}</td>
                <td>{{ item.记录编号 }}</td>
                <td>{{ item.请求时间 }}</td>
                <td>{{ item.原节点 ?? '—' }}</td>
                <td>{{ item.节点编号 ?? '—' }}</td>
                <td>{{ item.状态 }}</td>
                <td class="reason">{{ item.冲突说明 }}</td>
                <td>
                  <button
                    class="link"
                    type="button"
                    :disabled="item.状态 !== '待裁决'"
                    @click="adjudicate(item)"
                  >
                    保留原记录并接受新段
                  </button>
                </td>
              </tr>
              <tr v-if="!current.conflicts.length">
                <td colspan="9" class="empty-state">没有冲突，归档顺序与请求时间一致</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-else-if="activeTab === 'queue'">
          <table class="data-table">
            <thead>
              <tr>
                <th>队列编号</th>
                <th>数据集编号</th>
                <th>归档文件</th>
                <th>类型</th>
                <th>记录编号</th>
                <th>记录摘要</th>
                <th>节点编号</th>
                <th>裁决编号</th>
                <th>状态</th>
                <th>可执行动作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in queueRows" :key="item.队列编号">
                <td>{{ item.队列编号 }}</td>
                <td>{{ item.数据集编号 }}</td>
                <td>{{ item.归档文件 }}</td>
                <td>{{ item.类型 }}</td>
                <td>{{ item.记录编号 }}</td>
                <td>{{ item.记录摘要 }}</td>
                <td>{{ item.节点编号 ?? '—' }}</td>
                <td>{{ item.裁决编号 ?? '—' }}</td>
                <td>{{ item.状态 }}</td>
                <td class="row-actions">
                  <button class="link" type="button" @click="queueAction('确认交付', item)">确认交付</button>
                  <button class="link" type="button" @click="queueAction('关闭队列项', item)">关闭队列项</button>
                </td>
              </tr>
              <tr v-if="!queueRows.length">
                <td colspan="10" class="empty-state">审计交付待处理队列为空</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-else-if="activeTab === 'recheck'">
          <div class="filter-bar">
            <button class="btn primary" type="button" @click="runRecheck">复测：重复写入 + 一条迟到更正</button>
            <span class="inline-note">复测在数据集副本上执行，不改动正式归档与交付队列</span>
          </div>
          <div v-if="recheckResult">
            <p :class="recheckResult.ok ? 'ok-text' : 'error-text'">{{ recheckResult.message }}</p>
            <table class="data-table">
              <thead>
                <tr><th>检查项</th><th>结果</th><th>说明</th></tr>
              </thead>
              <tbody>
                <tr v-for="item in recheckResult.checks" :key="item.名称">
                  <td>{{ item.名称 }}</td>
                  <td :class="item.通过 ? 'ok-text' : 'error-text'">{{ item.通过 ? '通过' : '未通过' }}</td>
                  <td>{{ item.说明 }}</td>
                </tr>
              </tbody>
            </table>
            <table class="data-table">
              <thead>
                <tr><th>复测项</th><th>结果</th></tr>
              </thead>
              <tbody>
                <tr><td>主摘要</td><td>{{ recheckResult.主摘要 }}</td></tr>
                <tr><td>原节点</td><td>{{ recheckResult.原节点 }}</td></tr>
                <tr><td>重复写入</td><td>{{ recheckResult.重复写入.说明 }}</td></tr>
                <tr><td>迟到更正</td><td>{{ recheckResult.迟到更正.说明 }}</td></tr>
                <tr><td>导出记录数</td><td>{{ recheckResult.导出.记录数 }}</td></tr>
                <tr><td>导出首条时间</td><td>{{ recheckResult.导出.首条时间 }}</td></tr>
                <tr><td>导出摘要断点</td><td>{{ recheckResult.导出.摘要断点数 }}</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { fetchJson, request } from '@/api/client'

type Row = Record<string, any>

type Check = { 名称: string; 通过: boolean; 说明: string }

const ENDPOINT = '/api/audit'
const columns = ['数据集编号', '归档文件', '来源批次', '采集请求数', '主节点数', '更正段数', '摘要断点数', '首条时间', '末条时间', '状态']
const statuses = ['收集中', '待裁决', '已封存']
const tabs = [
  { key: 'nodes', label: '归档节点' },
  { key: 'export', label: '导出批次' },
  { key: 'conflicts', label: '冲突裁决' },
  { key: 'queue', label: '交付队列' },
  { key: 'recheck', label: '复测' },
] as const

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref({ keyword: '', status: '' })
const current = ref<Row | null>(null)
const activeTab = ref<(typeof tabs)[number]['key']>('nodes')
const nodeFilter = ref<'all' | 'main' | 'correction' | 'breakpoint'>('all')
const exportDetail = ref<Row | null>(null)
const recheckResult = ref<Row | null>(null)
const queueRows = ref<Row[]>([])

const stats = computed(() => [
  { label: '审计数据集', value: total.value },
  { label: '采集请求数', value: current.value?.采集请求数 ?? 0 },
  { label: '摘要断点', value: current.value?.摘要断点数 ?? 0 },
])

const verifyChecks = computed<Check[]>(() => current.value?.校验?.checks ?? [])

const visibleNodes = computed<Row[]>(() => {
  const nodes: Row[] = current.value?.nodes ?? []
  if (nodeFilter.value === 'main') return nodes.filter((node) => node.节点类型 === '主节点')
  if (nodeFilter.value === 'correction') return nodes.filter((node) => node.节点类型 === '更正段')
  if (nodeFilter.value === 'breakpoint') return nodes.filter((node) => node.断点)
  return nodes
})

function display(value: unknown): string {
  return value === null || value === undefined || value === '' ? '—' : String(value)
}

function resetFilters() {
  filters.value = { keyword: '', status: '' }
  void reload()
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams({
    ...(filters.value.keyword ? { keyword: filters.value.keyword } : {}),
    ...(filters.value.status ? { status: filters.value.status } : {}),
  }).toString()
  try {
    const payload = await fetchJson<{ items: Row[]; total: number }>(`${ENDPOINT}?${query}`)
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (rows.value.length && (!current.value || !rows.value.some((row) => row.id === current.value?.id))) {
      await select(rows.value[0])
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '日志审计数据集读取失败'
  }
}

async function select(row: Row) {
  errorMessage.value = ''
  exportDetail.value = null
  recheckResult.value = null
  try {
    current.value = await fetchJson<Row>(`${ENDPOINT}/${row.id}`)
    await loadQueue()
    if (activeTab.value === 'export') {
      await loadExport()
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '审计数据集明细读取失败'
  }
}

async function loadExport() {
  if (!current.value) return
  try {
    exportDetail.value = await fetchJson<Row>(`${ENDPOINT}/${current.value.id}/export`)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出详情读取失败'
  }
}

function downloadExport() {
  if (!exportDetail.value) return
  const blob = new Blob([JSON.stringify(exportDetail.value, null, 2)], {
    type: 'application/json;charset=utf-8',
  })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${exportDetail.value.导出批次}-${exportDetail.value.记录数}条.json`
  link.click()
  URL.revokeObjectURL(url)
}

async function loadQueue() {
  try {
    const payload = await fetchJson<{ items: Row[] }>(`${ENDPOINT}/queue?size=200`)
    queueRows.value = payload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '审计交付待处理队列读取失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? `${action}未生效`)
    }
    await reload()
    if (current.value?.id === row.id) {
      await select(row)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : `${action}失败`
  }
}

async function adjudicate(item: Row) {
  if (!current.value) return
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${current.value.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({
        action: '裁决冲突',
        裁决编号: item.裁决编号,
        裁决: '保留原记录并接受新段',
      }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? '裁决未生效')
    }
    await select(current.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '裁决失败'
  }
}

async function queueAction(action: string, item: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/queue/${item.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? `${action}未生效`)
    }
    await loadQueue()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : `${action}失败`
  }
}

async function runRecheck() {
  if (!current.value) return
  errorMessage.value = ''
  activeTab.value = 'recheck'
  try {
    const response = await request(`${ENDPOINT}/${current.value.id}/recheck`, {
      method: 'POST',
      body: JSON.stringify({}),
    })
    const payload = await response.json()
    if (!response.ok) {
      throw new Error(payload.detail ?? '复测未执行')
    }
    recheckResult.value = payload
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '复测失败'
  }
}

function openCreate() {
  errorMessage.value = '审计数据集建集入口尚未接入批次清单，可调用 POST /api/audit 按批次建立'
}

onMounted(reload)
</script>

<style scoped>
.row-active { background: #eef4ff; }
.detail-panel { margin-top: 20px; }
.detail-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
.detail-meta { display: flex; flex-direction: column; gap: 4px; color: var(--muted); font-size: 12px; text-align: right; }
.tab-bar { display: flex; gap: 6px; margin: 12px 0; }
.tab { border: 1px solid var(--border); background: #fff; border-radius: 6px; padding: 6px 12px; cursor: pointer; }
.tab.active { background: var(--brand); border-color: var(--brand); color: #fff; }
.digest { font-family: 'SFMono-Regular', Consolas, monospace; font-size: 12px; }
.check-card .check-note { display: block; color: var(--muted); font-size: 12px; margin-top: 4px; }
.reason { max-width: 280px; }
.inline-note { color: var(--muted); font-size: 12px; align-self: center; }
.ok-text { color: #067647; }
.filter-item select { padding: 4px 6px; }
</style>
