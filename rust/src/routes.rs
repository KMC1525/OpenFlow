//! Rotas já portadas para Rust. O que não está aqui é repassado ao worker Python (ver `app::App::to_worker`).

use crate::app::App;

pub fn register(_app: &mut App) {}
