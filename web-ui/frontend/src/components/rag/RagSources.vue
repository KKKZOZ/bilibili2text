<script setup>
  import { BookMarked, ExternalLink } from 'lucide-vue-next'
  import { resourceDisplayLabel, resourceUrl } from '../../utils/fileUtils'

  defineProps({ sources: { type: Array, default: () => [] } })

  const scorePercent = (score) => Math.round(score * 100)
  const scoreColor = (score) => {
    if (score >= 0.7) return '#0d9488'
    if (score >= 0.45) return '#0284c7'
    return '#64748b'
  }
</script>

<template>
  <section class="sources-section">
    <h3>
      <BookMarked :size="15" /><span>参考来源</span><b>{{ sources.length }}</b>
    </h3>
    <div class="sources-grid">
      <a
        v-for="(source, index) in sources"
        :id="`source-${index}`"
        :key="`${source.bvid}-${index}`"
        :href="resourceUrl(source.bvid)"
        target="_blank"
        rel="noopener noreferrer"
        class="source-card"
        :class="{ 'no-link': !resourceUrl(source.bvid) }"
      >
        <div class="source-card-top">
          <span class="source-index">{{ index + 1 }}</span>
          <div class="source-meta">
            <span class="source-title">{{
              source.title || source.bvid || '未知视频'
            }}</span>
            <span v-if="source.bvid" class="source-bvid">
              {{ resourceDisplayLabel(source.bvid) }}
              <ExternalLink v-if="resourceUrl(source.bvid)" :size="11" />
            </span>
          </div>
          <span
            class="score-pill"
            :style="{ '--score-color': scoreColor(source.score) }"
          >
            {{ scorePercent(source.score) }}%
          </span>
        </div>
        <div class="score-track">
          <div
            :style="{
              width: `${scorePercent(source.score)}%`,
              background: scoreColor(source.score)
            }"
          ></div>
        </div>
        <p>
          {{ source.text.slice(0, 220)
          }}{{ source.text.length > 220 ? '...' : '' }}
        </p>
      </a>
    </div>
  </section>
</template>

<style scoped>
  .sources-section {
    display: grid;
    gap: 12px;
  }

  h3 {
    display: flex;
    align-items: center;
    gap: 7px;
    margin: 0;
    color: var(--text-soft);
    font-size: 0.86rem;
  }

  h3 b {
    padding: 2px 6px;
    border-radius: 99px;
    background: var(--brand-soft);
    color: var(--brand-strong);
    font-size: 0.74rem;
  }

  .sources-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 12px;
  }

  .source-card {
    display: grid;
    gap: 8px;
    padding: 14px 16px;
    border: 1px solid var(--line);
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.82);
    color: inherit;
    text-decoration: none;
  }

  .source-card:hover:not(.no-link) {
    border-color: var(--brand);
    box-shadow: 0 8px 24px rgba(15, 23, 42, 0.1);
    transform: translateY(-2px);
  }

  .source-card-top {
    display: flex;
    align-items: flex-start;
    gap: 10px;
  }

  .source-index {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    border-radius: 6px;
    background: var(--brand-soft);
    color: var(--brand-strong);
    font-size: 0.74rem;
    font-weight: 800;
  }

  .source-meta {
    display: grid;
    flex: 1;
    min-width: 0;
  }

  .source-title {
    overflow: hidden;
    font-size: 0.86rem;
    font-weight: 700;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .source-bvid {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    color: var(--brand);
    font-size: 0.76rem;
  }

  .score-pill {
    color: var(--score-color);
    font-size: 0.74rem;
    font-weight: 700;
  }

  .score-track {
    height: 3px;
    overflow: hidden;
    border-radius: 99px;
    background: #e2e8f0;
  }

  .score-track div {
    height: 100%;
  }

  .source-card p {
    margin: 0;
    color: var(--text-muted);
    font-size: 0.82rem;
    line-height: 1.6;
  }

  @media (max-width: 640px) {
    .sources-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
