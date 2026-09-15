// web/apps/dashboards/components/Marca.js
// ---------------------------------------------------------------------------
// NUESTRO. El logo, en la cabecera de la barra lateral. La cromatica que
// adoptamos aguas arriba no tiene cabecera: la esquina superior izquierda del
// tablero ES el tope de esta barra flotante, y ahi va la marca.
//
// Son dos archivos porque son dos situaciones distintas, no dos tamanos del
// mismo dibujo: plegada la barra mide 48px y solo entra el simbolo; desplegada
// mide 180px y entra el lockup con la palabra y la bajada. Cual se ve lo
// decide el CSS (app/estilos/ajustes.css), con los mismos selectores de
// estado que usa el resto de la barra, para que aparezca y desaparezca a la
// vez que las etiquetas del menu.
//
// Son los PNG oficiales, con transparencia: 300x106 el lockup y 85x106 el
// simbolo. El CSS los mide por ALTO y deja el ancho en auto, para respetar
// esas proporciones sin repetirlas aqui. Si algun dia llegan en SVG, basta
// reemplazar los archivos y la extension en estas dos lineas.
// ---------------------------------------------------------------------------
export default function Marca() {
  return (
    <div className="side-marca">
      {/* El simbolo va con alt vacio y aria-hidden: es el mismo logo que el
          lockup, y anunciar los dos hacia que el lector de pantalla leyera
          "Profuturo" dos veces seguidas al entrar en la barra. */}
      <img className="side-marca-simbolo" src="/marca/profuturo-simbolo.png" alt="" aria-hidden="true" />
      <img className="side-marca-lockup" src="/marca/profuturo.png" alt="Profuturo" />
    </div>
  );
}
