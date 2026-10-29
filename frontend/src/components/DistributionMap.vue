<template>
  <div class="map-block">
    <div ref="container" class="map-canvas" role="img" :aria-label="`已确认记录地图，共 ${points.length} 个点位`" />
    <p class="map-hint">
      底图来自 OpenStreetMap，需要联网；点位和下方记录列表不依赖底图。GCJ-02/BD-09 坐标已转换为 WGS84 展示。
    </p>
  </div>
</template>

<script setup lang="ts">
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { onMounted, onUnmounted, ref, watch } from 'vue'

import type { AnalyticsMapPoint } from '../types'

const props = defineProps<{ points: AnalyticsMapPoint[] }>()
const container = ref<HTMLElement>()
let map: L.Map | null = null
let markers: L.LayerGroup | null = null

function popup(point: AnalyticsMapPoint): HTMLElement {
  const root = document.createElement('div')
  const title = document.createElement('strong')
  title.textContent = point.district || '区划未填写'
  const text = document.createElement('p')
  text.textContent = point.description
  text.style.margin = '4px 0 0'
  root.append(title, text)
  return root
}

function render() {
  if (!map || !markers) return
  markers.clearLayers()
  const valid = props.points.filter(point => Number.isFinite(point.map_latitude) && Number.isFinite(point.map_longitude))
  for (const point of valid) {
    L.circleMarker([point.map_latitude, point.map_longitude], {
      radius: 6, color: '#c0392b', weight: 2, fillColor: '#e74c3c', fillOpacity: 0.65,
    }).bindPopup(popup(point)).addTo(markers)
  }
  if (valid.length) {
    map.fitBounds(L.latLngBounds(valid.map(point => [point.map_latitude, point.map_longitude])).pad(0.2),
      { maxZoom: 12 })
  }
}

onMounted(() => {
  if (!container.value) return
  map = L.map(container.value, { scrollWheelZoom: false }).setView([35, 105], 4)
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19, attribution: '&copy; OpenStreetMap contributors',
  }).addTo(map)
  markers = L.layerGroup().addTo(map)
  render()
})

watch(() => props.points, render, { deep: true })
onUnmounted(() => {
  map?.remove()
  map = null
  markers = null
})
</script>

<style scoped>
.map-block {
  min-width: 0;
}

.map-canvas {
  width: 100%;
  height: 320px;
  border: 1px solid var(--border);
  border-radius: var(--r-control);
  z-index: 0;
}

.map-hint {
  margin: var(--s-2) 0 0;
  color: var(--muted);
  font-size: var(--fs-xs);
}
</style>
