import { createRouter, createWebHistory } from 'vue-router'

import Overview from '@/views/Overview.vue'
const Endpoint = () => import('@/views/endpoint/index.vue')
const Chain = () => import('@/views/chain/index.vue')
const Freq = () => import('@/views/freq/index.vue')
const Mapper = () => import('@/views/mapper/index.vue')
const Validator = () => import('@/views/validator/index.vue')
const Retry = () => import('@/views/retry/index.vue')
const Aggregator = () => import('@/views/aggregator/index.vue')
const Auth = () => import('@/views/auth/index.vue')
const Cache = () => import('@/views/cache/index.vue')
const Dump = () => import('@/views/dump/index.vue')
const Schedule = () => import('@/views/schedule/index.vue')
const Monitor = () => import('@/views/monitor/index.vue')
const Transform = () => import('@/views/transform/index.vue')
const Cleanse = () => import('@/views/cleanse/index.vue')
const Ratelimit = () => import('@/views/ratelimit/index.vue')
const Log = () => import('@/views/log/index.vue')
const Delta = () => import('@/views/delta/index.vue')
const Export = () => import('@/views/export/index.vue')
const Audit = () => import('@/views/audit/index.vue')

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview },
    { path: '/endpoint', name: 'endpoint', component: Endpoint },
    { path: '/chain', name: 'chain', component: Chain },
    { path: '/freq', name: 'freq', component: Freq },
    { path: '/mapper', name: 'mapper', component: Mapper },
    { path: '/validator', name: 'validator', component: Validator },
    { path: '/retry', name: 'retry', component: Retry },
    { path: '/aggregator', name: 'aggregator', component: Aggregator },
    { path: '/auth', name: 'auth', component: Auth },
    { path: '/cache', name: 'cache', component: Cache },
    { path: '/dump', name: 'dump', component: Dump },
    { path: '/schedule', name: 'schedule', component: Schedule },
    { path: '/monitor', name: 'monitor', component: Monitor },
    { path: '/transform', name: 'transform', component: Transform },
    { path: '/cleanse', name: 'cleanse', component: Cleanse },
    { path: '/ratelimit', name: 'ratelimit', component: Ratelimit },
    { path: '/log', name: 'log', component: Log },
    { path: '/delta', name: 'delta', component: Delta },
    { path: '/export', name: 'export', component: Export },
    { path: '/audit', name: 'audit', component: Audit },
  ],
})

export default router
