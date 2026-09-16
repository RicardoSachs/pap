// web/apps/dashboards/components/DateRangePicker.js
// ---------------------------------------------------------------------------
// Shared From/To date-range selector — the common date-selection pattern for
// every dashboard (extracted from the original Price Viewer inputs).
//
// Renders two `.field` blocks so it drops straight into the existing `.controls`
// flex row with identical layout/spacing/styling. Uses native <input type="date">
// (same browser calendar + open/close behavior everywhere). `min`/`max` are wired
// so From <= To is enforced consistently across dashboards.
//
// Props:
//   from, to            current ISO dates ('YYYY-MM-DD')
//   onFromChange, onToChange   setters called with the new ISO date
//   min, max            optional bounds for the whole range
//   fromLabel, toLabel  optional label overrides (default 'From' / 'To')
// ---------------------------------------------------------------------------
'use client';

export default function DateRangePicker({
  from,
  to,
  onFromChange,
  onToChange,
  min,
  max,
  fromLabel = 'From',
  toLabel = 'To',
}) {
  return (
    <>
      <div className="field">
        <label>{fromLabel}</label>
        <input
          type="date"
          value={from || ''}
          min={min}
          max={to || max}
          onChange={(e) => onFromChange(e.target.value)}
        />
      </div>
      <div className="field">
        <label>{toLabel}</label>
        <input
          type="date"
          value={to || ''}
          min={from || min}
          max={max}
          onChange={(e) => onToChange(e.target.value)}
        />
      </div>
    </>
  );
}
