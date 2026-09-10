<template>
  <div class="hazard-overlay">
    <el-empty
      v-if="!imagesWithUrls.length"
      description="暂无原始图片可用于隐患定位"
    />

    <div v-else class="overlay-grid">
      <div
        v-for="image in imagesWithUrls"
        :key="image.id"
        class="overlay-item"
      >
        <div class="overlay-item-head">
          <span class="overlay-filename">{{ image.filename }}</span>
          <el-tag
            :type="boxesForImage(image.id).length ? 'success' : 'info'"
            size="small"
          >
            {{ boxesForImage(image.id).length ? `${boxesForImage(image.id).length} 个可靠框` : '暂无可靠 bbox' }}
          </el-tag>
        </div>
        <div
          v-if="naturalSizes[image.id]"
          class="bbox-stage"
          :style="stageStyle(image.id)"
        >
          <img :src="image.url" class="bbox-img" alt="现场图片" />
          <div
            v-for="box in boxesForImage(image.id)"
            :key="box.key"
            class="bbox-overlay"
            :style="boxStyle(box, image.id)"
          >
            <span class="bbox-label">{{ box.category }}</span>
          </div>
        </div>
        <div v-else class="bbox-loading">
          正在加载图片以校验 bbox 坐标：{{ image.filename }}
        </div>
      </div>
    </div>

    <p v-if="skippedBoxLocations.length" class="overlay-note">
      有 {{ skippedBoxLocations.length }} 处 location 缺少可靠 bbox 或 image_id 未对应上传图片，已按真实文本展示，未绘制。
    </p>
    <p v-if="imagesWithUrls.length && !hasAnyPlausibleBox" class="overlay-note">
      当前未获得可靠 bbox，不绘制任何定位框，避免伪造坐标。
    </p>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, watch } from 'vue'

import type {
  Assessment,
  AssessmentImage,
  Finding,
  FindingLocation,
} from '../types'

const props = defineProps<{
  assessment: Assessment
}>()

interface BoxEntry {
  key: string
  category: string
  description: string
  bbox: number[]
}

const naturalSizes = reactive<
  Record<string, { width: number; height: number }>
>({})

const imagesWithUrls = computed(() =>
  props.assessment.images.filter(
    (image) => image.image_kind === 'original' && image.url,
  ),
)

function loadSize(image: AssessmentImage) {
  if (!image.url || naturalSizes[image.id]) return
  const el = new Image()
  el.onload = () => {
    naturalSizes[image.id] = {
      width: el.naturalWidth,
      height: el.naturalHeight,
    }
  }
  el.src = image.url
}

watch(
  imagesWithUrls,
  (images) => {
    for (const image of images) loadSize(image)
  },
  { immediate: true },
)

interface LocatedFinding {
  finding: Finding
  location: FindingLocation
}

const locatedFindings = computed<LocatedFinding[]>(() =>
  (props.assessment.findings ?? []).flatMap((finding) =>
    (finding.locations ?? []).map((location) => ({ finding, location })),
  ),
)

function plausibleBox(
  bbox: number[] | undefined,
  natural?: { width: number; height: number },
) {
  if (!bbox || bbox.length !== 4) return false
  if (bbox.some((value) => !Number.isFinite(value))) return false
  if (!natural) return false
  if (bbox.every((value) => value >= 0 && value <= 1)) return true
  const [x1, y1, x2, y2] = bbox
  return (
    x1 >= 0 &&
    y1 >= 0 &&
    x2 > x1 &&
    y2 > y1 &&
    x2 <= natural.width + 1 &&
    y2 <= natural.height + 1
  )
}

function boxesForImage(imageId: string): BoxEntry[] {
  const natural = naturalSizes[imageId]
  return locatedFindings.value
    .filter(
      (entry) =>
        entry.location.image_id === imageId &&
        plausibleBox(entry.location.bbox, natural),
    )
    .map((entry) => ({
      key: `${entry.finding.finding_id}-${entry.location.image_id}`,
      category: entry.finding.category,
      description: entry.finding.description,
      bbox: entry.location.bbox as number[],
    }))
}

function stageStyle(imageId: string) {
  const natural = naturalSizes[imageId]
  if (!natural) return {}
  return {
    aspectRatio: `${natural.width} / ${natural.height}`,
  }
}

function boxStyle(box: BoxEntry, imageId: string) {
  const natural = naturalSizes[imageId]
  if (!natural) return {}
  const [x1, y1, x2, y2] = box.bbox
  const normalized = box.bbox.every((value) => value >= 0 && value <= 1)
  const width = normalized ? 1 : natural.width
  const height = normalized ? 1 : natural.height
  return {
    left: `${(x1 / width) * 100}%`,
    top: `${(y1 / height) * 100}%`,
    width: `${((x2 - x1) / width) * 100}%`,
    height: `${((y2 - y1) / height) * 100}%`,
  }
}

const skippedBoxLocations = computed(() =>
  locatedFindings.value.filter((entry) => {
    if (!entry.location.image_id) return true
    const image = imagesWithUrls.value.find(
      (item) => item.id === entry.location.image_id,
    )
    if (!image) return true
    return !plausibleBox(entry.location.bbox, naturalSizes[image.id])
  }),
)

const hasAnyPlausibleBox = computed(() =>
  imagesWithUrls.value.some((image) => boxesForImage(image.id).length > 0),
)
</script>

<style scoped>
.hazard-overlay {
  min-height: 80px;
}

.overlay-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 14px;
}

.overlay-item {
  min-width: 0;
}

.overlay-item-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.overlay-filename {
  color: #334155;
  font-size: 12px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bbox-stage {
  position: relative;
  width: 100%;
  max-width: 420px;
  overflow: hidden;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #f8fafc;
}

.bbox-img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.bbox-overlay {
  position: absolute;
  border: 2px solid #ef4444;
  border-radius: 2px;
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.8);
}

.bbox-label {
  position: absolute;
  top: -20px;
  left: -2px;
  padding: 1px 6px;
  background: #ef4444;
  color: #ffffff;
  font-size: 11px;
  border-radius: 3px;
  white-space: nowrap;
}

.bbox-loading {
  min-height: 120px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px dashed #cbd5e1;
  border-radius: 6px;
  color: #94a3b8;
  font-size: 12px;
}

.overlay-note {
  margin: 12px 0 0;
  padding: 8px 10px;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 6px;
  color: #b45309;
  font-size: 12px;
}
</style>
