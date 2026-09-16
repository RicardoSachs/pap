// web/apps/dashboards/components/PlotlyChart.js
// ---------------------------------------------------------------------------
// Client-only Plotly wrapper. plotly.js touches `window` at module load, so this
// file is always imported via next/dynamic({ ssr: false }) -- never server-side.
// Uses the prebuilt dist-min bundle + react-plotly.js factory (no source build).
//
// Theme: colors come from the live CSS tokens (chartTheme) and re-read on toggle
// (useThemeVersion). Pages pass STRUCTURAL axis props (spikes, titles, zeroline)
// only; this component injects the themed colors via a shallow axis merge.
// ---------------------------------------------------------------------------
'use client';

import createPlotlyComponent from 'react-plotly.js/factory';
import Plotly from 'plotly.js-dist-min';
import { chartTheme, useThemeVersion } from '../lib/theme';

const Plot = createPlotlyComponent(Plotly);

const FONT = "var(--font-plex), 'IBM Plex Mono', monospace";

function buildBase(t) {
  return {
    margin: { l: 60, r: 20, t: 30, b: 50 },
    font: { family: FONT, size: 12, color: t.text },
    paper_bgcolor: t.surface,
    plot_bgcolor: t.surface,
    legend: { orientation: 'h', y: -0.2, font: { color: t.muted } },
    hovermode: 'closest',
    hoverlabel: {
      bgcolor: t.panel,
      bordercolor: t.border,
      font: { family: FONT, size: 12, color: t.text },
      align: 'left',
      namelength: -1,
    },
  };
}

function mergeAxis(themeAxis, page) {
  return { ...themeAxis, ...(page || {}), tickfont: { ...themeAxis.tickfont, ...(page?.tickfont || {}) } };
}

export default function PlotlyChart({ data, layout = {}, style, config = {}, onHover, onUnhover, onLegendClick, onLegendDoubleClick, onInitialized, onSelected, onClick, onClickAnnotation }) {
  useThemeVersion(); // re-render when the theme toggles so tokens are re-read
  const t = chartTheme();
  const themeAxis = {
    gridcolor: t.border, zerolinecolor: t.muted, linecolor: t.border,
    spikecolor: t.muted, tickfont: { color: t.muted },
  };
  const merged = {
    ...buildBase(t),
    ...layout,
    xaxis: mergeAxis(themeAxis, layout.xaxis),
    yaxis: mergeAxis(themeAxis, layout.yaxis),
  };

  return (
    <Plot
      data={data}
      layout={merged}
      config={{ displayModeBar: false, responsive: true, ...config }}
      style={{ width: '100%', height: '420px', ...style }}
      useResizeHandler
      onInitialized={onInitialized}
      onHover={onHover}
      onUnhover={onUnhover}
      onClick={onClick}
      onLegendClick={onLegendClick}
      onLegendDoubleClick={onLegendDoubleClick}
      onSelected={onSelected}
    />
  );
}
