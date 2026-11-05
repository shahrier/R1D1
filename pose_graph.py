"""Small SE(2) pose graph: odometry edges plus explicitly verified revisit constraints."""
import math
import numpy as np


def wrap(angle):
    return (angle + math.pi) % (2 * math.pi) - math.pi


def relative(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    c, s = math.cos(a[2]), math.sin(a[2])
    return np.array([c * dx + s * dy, -s * dx + c * dy, wrap(b[2] - a[2])])


def optimize(poses, edges, iterations=12):
    output = np.asarray(poses, dtype=float).copy()
    if len(output) < 2 or not edges:
        return output.tolist()
    variables = 3 * (len(output) - 1)
    for _ in range(iterations):
        normal = np.eye(variables) * 1e-6
        rhs = np.zeros(variables)
        for edge in edges:
            i, j = edge['from'], edge['to']
            a, b = output[i], output[j]
            error = relative(a, b) - np.asarray(edge['measurement'])
            error[2] = wrap(error[2])
            c, s = math.cos(a[2]), math.sin(a[2])
            dx, dy = b[0] - a[0], b[1] - a[1]
            ja = np.array([[-c, -s, -s * dx + c * dy],
                           [s, -c, -c * dx - s * dy], [0, 0, -1.]])
            jb = np.array([[c, s, 0], [-s, c, 0], [0, 0, 1.]])
            sigma = np.asarray(edge.get('sigma', [.03, .03, math.radians(3)]))
            robust = min(1., 3. / max(float(np.linalg.norm(error / sigma)), 1e-9))
            weight = np.diag(robust / sigma ** 2)
            blocks = [(i, ja), (j, jb)]
            for index, jacobian in blocks:
                if index == 0:
                    continue
                start = 3 * (index - 1)
                rhs[start:start + 3] += jacobian.T @ weight @ error
                for other, other_jacobian in blocks:
                    if other == 0:
                        continue
                    column = 3 * (other - 1)
                    normal[start:start + 3, column:column + 3] += jacobian.T @ weight @ other_jacobian
        try:
            delta = np.linalg.solve(normal, -rhs)
        except np.linalg.LinAlgError:
            break
        output[1:] += delta.reshape(-1, 3)
        output[:, 2] = [wrap(value) for value in output[:, 2]]
        if float(np.linalg.norm(delta)) < 1e-5:
            break
    return output.tolist()
