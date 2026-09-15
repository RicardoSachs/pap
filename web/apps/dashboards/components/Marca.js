// web/apps/dashboards/components/Marca.js
// ---------------------------------------------------------------------------
// NUESTRO. El logo, en la cabecera de la barra lateral. La cromatica que
// adoptamos aguas arriba no tiene cabecera: la esquina superior izquierda del
// tablero ES el tope de esta barra flotante, y ahi va la marca.
//
// Son dos archivos porque son dos situaciones distintas, no dos tamanos del
// mismo dibujo: plegada la barra mide 48px y solo entra el simbolo; desplegada
// mide 180px y entra el lockup con la palabra. Cual se ve lo decide el CSS
// (app/estilos/ajustes.css), con los mismos selectores de estado que usa el
// resto de la barra, para que aparezca y desaparezca a la vez que las
// etiquetas del menu.
//
// Para poner el archivo oficial basta reemplazar los dos SVG de
// public/marca/ conservando el nombre; este componente no mira el formato.
// ---------------------------------------------------------------------------
export default function Marca() {
  return (
    <div className="side-marca">
      {/* alt vacio y aria-hidden: el nombre ya lo dice el <title> del SVG, y
          repetirlo hacia que el lector de pantalla leyera "Profuturo" dos
          veces seguidas al entrar en la barra. */}
      <img className="side-marca-simbolo" src="/marca/profuturo-simbolo.svg" alt="" aria-hidden="true" />
      <img className="side-marca-lockup" src="/marca/profuturo.svg" alt="Profuturo" />
    </div>
  );
}
