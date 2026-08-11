//! A* over an occupancy grid, and what a robot radius does to the route.
//!
//! Two plans across the same map: one for a point robot, one with the obstacles
//! inflated by an inscribed radius so a body has to keep its distance.
//!
//! A note on what you are looking at, because the first version of this demo
//! got it wrong: `planning::plan` returns **turn points only**, and excludes the
//! start because the robot is already there. The `*` marks are therefore
//! waypoints, not a traced path — a straight run of twelve cells appears as one
//! mark at each end. Drawing them as if they were a dense path made a correct
//! plan look broken.

use anyhow::Result;
use obc_navigation::costmap::{inflate, plan_inflated};
use obc_navigation::planning::{plan, Cell, OccupancyGrid};

const W: usize = 21;
const H: usize = 11;

fn map() -> OccupancyGrid {
    // 0.5 m cells, origin at (0,0): a 10.5 m x 5.5 m room.
    let mut g = OccupancyGrid::new(0.0, 0.0, 0.5, W, H);
    // A wall down the middle, open along the bottom three rows.
    for y in 3..H {
        g.set(10, y, Cell::Occupied);
    }
    g
}

fn draw(
    grid: &OccupancyGrid,
    path: &[(f64, f64)],
    start: (usize, usize),
    goal: (usize, usize),
    title: &str,
) {
    let waypoints: Vec<(usize, usize)> = path
        .iter()
        .filter_map(|&(x, y)| grid.world_to_cell(x, y))
        .collect();
    println!("{title}");
    for y in (0..H).rev() {
        let mut row = String::from("  ");
        for x in 0..W {
            row.push(match () {
                _ if (x, y) == start => 'S',
                _ if (x, y) == goal => 'G',
                _ if waypoints.contains(&(x, y)) => '*',
                _ if grid.get(x, y) == Cell::Occupied => '#',
                _ => '.',
            });
        }
        println!("{row}");
    }
    println!("  {} waypoints\n", path.len());
}

pub fn run() -> Result<()> {
    let grid = map();
    let (sx, sy) = (1usize, 5usize);
    let (gx, gy) = (19usize, 5usize);
    let start = grid.cell_center(sx, sy);
    let goal = grid.cell_center(gx, gy);

    println!(
        "a {W}x{H} grid at {} m/cell. One wall (#), open along the bottom.\n\
         S start, G goal, * turn point.\n",
        grid.resolution()
    );

    match plan(&grid, start, goal) {
        Some(p) => draw(
            &grid,
            &p,
            (sx, sy),
            (gx, gy),
            "point robot — A* on the raw grid:",
        ),
        None => println!("no path, which would be a bug: the bottom is open\n"),
    }

    // Lethal within the inscribed radius, decaying cost out to the inflation
    // radius. A body cannot graze the wall the way a point can.
    let field = inflate(&grid, 0.6, 1.2, 2.0);
    match plan_inflated(&grid, &field, start, goal) {
        Some(p) => draw(
            &grid,
            &p,
            (sx, sy),
            (gx, gy),
            "0.6 m robot — same A*, costs inflated around the wall:",
        ),
        None => println!(
            "0.6 m robot: no route with this clearance. The opening admits a point\n\
             and not this body, and the planner says so rather than driving into it.\n"
        ),
    }

    println!(
        "Both routes exist, and they are not the same route. Compare where each\n\
         one crosses: the point robot rounds the wall as tightly as the grid\n\
         allows, the 0.6 m robot swings lower, because the cells beside the wall\n\
         now cost more than the detour does. Fewer turn points is not a shorter\n\
         path — it is a straighter one."
    );
    Ok(())
}
