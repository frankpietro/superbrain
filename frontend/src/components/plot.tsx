import createPlotlyComponent from "react-plotly.js/factory";
// @ts-expect-error - plotly.js-cartesian-dist-min ships CJS without types;
// using the cartesian subset instead of plotly.js-dist keeps the bundle
// about 3 MB smaller.
import PlotlyCartesian from "plotly.js-cartesian-dist-min";
import type { Data, Layout, Config } from "plotly.js";

// The factory signature types Plotly loosely; we narrow back to the
// official types on the component boundary below.
const Plot = createPlotlyComponent(
  PlotlyCartesian as unknown as Parameters<typeof createPlotlyComponent>[0],
);

interface PlotProps {
  data: Data[];
  layout?: Partial<Layout>;
  config?: Partial<Config>;
  className?: string;
  ariaLabel?: string;
}

const defaultLayout: Partial<Layout> = {
  margin: { t: 24, r: 16, b: 32, l: 40 },
  paper_bgcolor: "rgba(0,0,0,0)",
  plot_bgcolor: "rgba(0,0,0,0)",
  font: { family: "Inter, system-ui, sans-serif", size: 12 },
  showlegend: false,
};

const defaultConfig: Partial<Config> = {
  displayModeBar: false,
  responsive: true,
};

export function Chart({ data, layout, config, className, ariaLabel }: PlotProps) {
  return (
    <div className={className} role="img" aria-label={ariaLabel ?? "chart"}>
      <Plot
        data={data}
        layout={{ ...defaultLayout, ...layout }}
        config={{ ...defaultConfig, ...config }}
        useResizeHandler
        style={{ width: "100%", height: "100%" }}
      />
    </div>
  );
}
