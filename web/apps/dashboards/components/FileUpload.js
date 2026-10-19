// web/apps/dashboards/components/FileUpload.js
// ---------------------------------------------------------------------------
// OURS. Uploading a file, the same in every site that offers it.
//
// Two panels, act on the left and see on the right:
//
//   LEFT   title, what is expected, and a header always in the same order:
//          [format] [↓ Template] [file]. Below, the site's own fields
//          (extra), the buttons (actions) and the echo of what happened.
//   RIGHT  the preview of what the file brings, with an empty state that
//          says what will appear there. Nothing seen on the right has
//          touched the database yet; the panel says so.
//
// This component does NOT know what is inside the file nor how it loads:
// every site has its endpoint, its report and its flow (review and load; or
// review and choose between completing and correcting). What it unifies is
// where everything lives, so the operator who learned to load valor cuota
// knows how to load the Tradebook without looking again. That is why the
// <input type=file> is exposed with forwardRef: the site keeps reading the
// file the way it did.
// ---------------------------------------------------------------------------
'use client';

import { forwardRef } from 'react';

import Echo from './Echo';
import FileFormat from './FileFormat';
import { apiUrl } from '../lib/spp';

const FileUpload = forwardRef(function FileUpload({
  title,
  description,
  format,
  template = null,
  accept = '.xlsx,.xls,.csv',
  fileName = null,
  onChange,
  extra = null,
  actions = null,
  echo = '',
  footer = null,
  previewTitle = 'Vista previa del archivo',
  previewStatus = null,
  preview = null,
  previewEmpty = 'Elige un archivo y aquí verás lo que trae, antes de que nada toque la base.',
}, ref) {
  return (
    <div className="spp-two-up">
      <div className="panel">
        <div className="panel-title">{title}</div>
        {description && <p className="page-sub">{description}</p>}

        {/* The fixed header. The icon goes FIRST: it is the question one
            asks before choosing the file, not after. */}
        <div className="controls upload-header">
          <FileFormat formatKey={format} />
          {template && (
            <a className="btn" href={apiUrl(template)}>↓ Plantilla · XLSX</a>
          )}
          <input ref={ref} type="file" accept={accept} className="date-input"
            aria-label="Archivo a cargar" onChange={onChange} />
          {/* No sheet selector: the reader takes the first one. A "Hoja
              (opcional)" box was one more question for the operator and
              almost never had an answer other than the first. */}
          {fileName && <span className="page-sub dim" style={{ margin: 0 }}>{fileName}</span>}
        </div>

        {extra}
        {actions && <div className="controls" style={{ marginTop: 12 }}>{actions}</div>}
        <Echo echo={echo} />
        {footer && <div className="controls" style={{ marginTop: 12 }}>{footer}</div>}
      </div>

      <div className="panel">
        <div className="panel-title">{previewTitle}</div>
        {preview ? (
          <>
            {previewStatus && <p className="page-sub">{previewStatus}</p>}
            {preview}
          </>
        ) : (
          <p className="page-sub dim">{previewEmpty}</p>
        )}
      </div>
    </div>
  );
});

export default FileUpload;
