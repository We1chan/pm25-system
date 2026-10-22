<script setup>
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import * as echarts from 'echarts'
const props = defineProps({ option: Object, height: { default: '300px' }, label: { default: '数据图表' } })
const emit = defineEmits(['select'])
const element = ref(null)
let chart, observer, resizeFrame
function measurable() { return element.value?.clientWidth > 0 && element.value?.clientHeight > 0 }
function update() {
  if (!measurable()) return
  if (!chart) {
    chart = echarts.init(element.value)
    chart.on('click', data => emit('select', data))
  }
  if (props.option) chart.setOption(props.option, { notMerge: true })
}
onMounted(() => {
  observer = new ResizeObserver(() => {
    cancelAnimationFrame(resizeFrame)
    resizeFrame = requestAnimationFrame(() => {
      if (!measurable()) return
      if (!chart) update()
      else if (!chart.isDisposed()) chart.resize()
    })
  })
  observer.observe(element.value)
  update()
})
watch(() => props.option, update, { deep: false })
onBeforeUnmount(() => { observer?.disconnect(); cancelAnimationFrame(resizeFrame); chart?.dispose(); chart = undefined })
</script>
<template><div ref="element" class="chart" :style="{ height }" role="img" :aria-label="label"></div></template>
