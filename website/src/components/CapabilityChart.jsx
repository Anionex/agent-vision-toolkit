import { useEffect, useRef } from 'react'
import {
  BarController,
  BarElement,
  CategoryScale,
  Chart,
  Legend,
  LinearScale,
  Tooltip,
} from 'chart.js'

Chart.register(BarController, BarElement, CategoryScale, LinearScale, Tooltip, Legend)

const toolStyles = [
  { id: 'glance', label: 'glance', color: '#2f5bc4', muted: 'rgba(47, 91, 196, 0.18)' },
  { id: 'ground', label: 'ground', color: '#4777df', muted: 'rgba(71, 119, 223, 0.18)' },
  { id: 'detect', label: 'detect', color: '#6a98ef', muted: 'rgba(106, 152, 239, 0.18)' },
  { id: 'trace', label: 'trace', color: '#73b9e8', muted: 'rgba(115, 185, 232, 0.2)' },
  { id: 'crop', label: 'crop', color: '#8fcfd3', muted: 'rgba(143, 207, 211, 0.22)' },
]

function CapabilityChart({ scenarios, activeIndex, onSelect }) {
  const canvasRef = useRef(null)

  useEffect(() => {
    if (!canvasRef.current) return undefined

    const chart = new Chart(canvasRef.current.getContext('2d'), {
      type: 'bar',
      data: {
        labels: scenarios.map((scenario) => scenario.shortLabel),
        datasets: toolStyles.map((tool) => ({
          label: tool.label,
          data: scenarios.map((scenario) => (scenario.tools.includes(tool.id) ? 1 : 0)),
          backgroundColor: scenarios.map((_, index) => index === activeIndex ? tool.color : tool.muted),
          borderWidth: 0,
          borderRadius: 7,
          borderSkipped: false,
          barPercentage: 0.74,
          categoryPercentage: 0.72,
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        indexAxis: 'y',
        interaction: { mode: 'index', intersect: false },
        animation: { duration: 650, easing: 'easeOutQuart' },
        onHover(event, elements) {
          event.native.target.style.cursor = elements.length ? 'pointer' : 'default'
        },
        onClick(_event, elements) {
          if (elements.length) onSelect(elements[0].index)
        },
        scales: {
          x: {
            stacked: true,
            beginAtZero: true,
            max: toolStyles.length,
            display: false,
            grid: { display: false },
            border: { display: false },
          },
          y: {
            stacked: true,
            grid: { display: false },
            border: { display: false },
            ticks: {
              color: '#41517a',
              font: {
                family: "Inter, ui-sans-serif, system-ui, -apple-system, 'PingFang SC', sans-serif",
                size: 12,
                weight: 600,
              },
              padding: 10,
            },
          },
        },
        plugins: {
          legend: {
            position: 'bottom',
            align: 'start',
            labels: {
              color: '#627092',
              usePointStyle: true,
              pointStyle: 'rectRounded',
              boxWidth: 9,
              boxHeight: 9,
              padding: 16,
              font: {
                family: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
                size: 11,
              },
            },
          },
          tooltip: {
            backgroundColor: '#0b1b49',
            titleColor: '#ffffff',
            bodyColor: '#dce8ff',
            padding: 12,
            cornerRadius: 10,
            displayColors: true,
            boxPadding: 5,
            filter: (item) => item.raw > 0,
            callbacks: {
              title: (items) => `${items[0].label} 推荐链路`,
              label: (item) => ` ${item.dataset.label}`,
            },
          },
        },
      },
    })

    return () => chart.destroy()
  }, [activeIndex, onSelect, scenarios])

  return (
    <div className="capability-chart">
      <canvas ref={canvasRef} role="img" aria-label="不同视觉场景所调用工具的横向堆叠条形图">
        不同视觉场景的工具调用关系图。
      </canvas>
    </div>
  )
}

export default CapabilityChart
