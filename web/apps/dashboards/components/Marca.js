// web/apps/dashboards/components/Marca.js
// ---------------------------------------------------------------------------
// NUESTRO. El logo, en la cabecera de la barra lateral. La cromatica que
// adoptamos aguas arriba no tiene cabecera: la esquina superior izquierda del
// tablero ES el tope de esta barra flotante, y ahi va la marca.
//
// Mientras no haya logo, esto no ocupa sitio: la barra empieza en Home, sin
// hueco reservado ni separador suelto. Cuando aparezca una imagen en
// public/marca/, se muestra sola. Por eso el alto y el separador dependen de
// que algo haya cargado de verdad, no de que el archivo este declarado.
//
// Cual archivo es lo dice la API (/api/marca), no una ruta escrita aqui. Es a
// proposito: en las maquinas donde esto corre no hay Node, asi que un nombre
// fijo obligaria a recompilar para estrenar un logo, y probar-y-fallar con
// <img> dejaria un 404 por carga en el log que el operador lee cuando algo va
// mal de verdad. Preguntando, el operador suelta el archivo y ya.
// ---------------------------------------------------------------------------
'use client';

import { useEffect, useState } from 'react';

export default function Marca() {
  const [marca, setMarca] = useState(null);

  useEffect(() => {
    let vigente = true;
    fetch('/api/marca')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (vigente) setMarca(d); })
      // Sin logo se ve exactamente igual que con la API caida, y esa es la
      // lectura correcta: el logo nunca es motivo para avisar de nada.
      .catch(() => {});
    return () => { vigente = false; };
  }, []);

  if (!marca || (!marca.simbolo && !marca.lockup)) return null;

  return (
    <>
      <div className="side-marca">
        {/* El simbolo va con alt vacio y aria-hidden: es el mismo logo que el
            lockup, y anunciar los dos hacia que el lector de pantalla leyera
            el nombre dos veces seguidas al entrar en la barra. */}
        {marca.simbolo && (
          <img className="side-marca-simbolo" src={marca.simbolo} alt="" aria-hidden="true" />
        )}
        {marca.lockup && (
          <img className="side-marca-lockup" src={marca.lockup} alt="Profuturo" />
        )}
      </div>
      <div className="side-sep" />
    </>
  );
}
