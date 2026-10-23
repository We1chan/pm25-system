<script setup>
/*
 * 内容面板：小标题（kicker）+ 标题 + 右上角操作区 + 正文 + 底部说明。
 * 底部说明用于写数据口径和使用边界，保持每张图"说清楚自己是什么"。
 */
defineProps({
  kicker: { type: String, default: '' },
  title: { type: String, default: '' },
  note: { type: String, default: '' },
})
</script>

<template>
  <section class="panel">
    <header v-if="title || $slots.actions" class="panel-head">
      <div>
        <p v-if="kicker" class="panel-kicker">{{ kicker }}</p>
        <h2 v-if="title">{{ title }}</h2>
      </div>
      <div v-if="$slots.actions" class="panel-actions">
        <slot name="actions" />
      </div>
    </header>
    <slot />
    <div v-if="note || $slots.note" class="panel-note">
      <slot name="note">{{ note }}</slot>
    </div>
  </section>
</template>
