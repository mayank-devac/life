/* The memory-hungry hot path of Life in Life, in plain C (C99, any OS, no dependencies).
 *
 * Zoomed in (and always in hover mode) every frame does two things:
 *     1. step the inner world of every live cell on screen
 *     2. turn those inner worlds into one RGBA image for the GPU
 * In numpy each of those builds several big temporary arrays per frame (fancy-index
 * copies, neighbour sums, a 5-D image, a bytes copy of it...). Megabytes of churn, 30 times
 * a second, and the allocator rarely hands it back to the OS, so the process keeps
 * growing. Here both run in place: no allocation at all per frame.
 *
 * Works on any buffer (numpy arrays, bytearrays), so numpy stays the data model and the
 * pure-numpy code in world.py / render.py remains as a fallback when this isn't built.
 */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdint.h>
#include <string.h>
#include <time.h>

#define MAX_M 64  /* largest inner world side (config.MICRO_SIZE is 16) */

/* ---------------------------------------------------------------- random numbers */
static uint64_t rng = 0x9E3779B97F4A7C15ULL;

static inline uint64_t next_rand(void)  /* xorshift64*: fast, good enough for seeding */
{
    rng ^= rng >> 12;
    rng ^= rng << 25;
    rng ^= rng >> 27;
    return rng * 0x2545F4914F6CDD1DULL;
}

/* Fill n cells: alive (1) with probability threshold / 256. */
static void random_cells(uint8_t *w, Py_ssize_t n, unsigned threshold)
{
    Py_ssize_t i = 0;
    while (i < n) {
        uint64_t r = next_rand();
        for (int k = 0; k < 8 && i < n; k++, i++, r >>= 8)
            w[i] = (uint8_t)((r & 0xFF) < threshold);
    }
}

/* ---------------------------------------------------------------- one inner world */
/* Step an m x m world (edges wrap) in place, `tmp` is m*m bytes of scratch.
 * `birth` / `survive` are bit masks: bit n set = n neighbours bring a cell to life / keep
 * it alive. Returns how many cells are alive afterwards. */
static int step_world(uint8_t *w, uint8_t *tmp, int m, unsigned birth, unsigned survive)
{
    int alive = 0;
    for (int i = 0; i < m; i++) {
        const uint8_t *up = w + ((i + m - 1) % m) * m;
        const uint8_t *row = w + i * m;
        const uint8_t *down = w + ((i + 1) % m) * m;
        for (int j = 0; j < m; j++) {
            int l = (j + m - 1) % m, r = (j + 1) % m;
            int n = up[l] + up[j] + up[r] + row[l] + row[r] + down[l] + down[j] + down[r];
            uint8_t next = (uint8_t)(((row[j] ? survive : birth) >> n) & 1u);
            tmp[i * m + j] = next;
            alive += next;
        }
    }
    memcpy(w, tmp, (size_t)m * m);
    return alive;
}

/* ---------------------------------------------------------------- helpers */
static int get_buffer(PyObject *obj, Py_buffer *view, int writable, Py_ssize_t need, const char *name)
{
    int flags = PyBUF_C_CONTIGUOUS | (writable ? PyBUF_WRITABLE : 0);
    if (PyObject_GetBuffer(obj, view, flags) < 0)
        return -1;
    if (view->len < need) {
        PyErr_Format(PyExc_ValueError, "%s: buffer has %zd bytes, needs %zd", name, view->len, need);
        PyBuffer_Release(view);
        return -1;
    }
    return 0;
}

static int check_region(Py_ssize_t size, Py_ssize_t *r0, Py_ssize_t *r1, Py_ssize_t *c0, Py_ssize_t *c1)
{
    if (*r0 < 0) *r0 = 0;
    if (*c0 < 0) *c0 = 0;
    if (*r1 > size) *r1 = size;
    if (*c1 > size) *c1 = size;
    return *r1 > *r0 && *c1 > *c0;
}

/* ---------------------------------------------------------------- Python API */
PyDoc_STRVAR(step_inner_doc,
"step_inner(inner, macro, size, m, region, birth, survive, threshold)\n"
"\n"
"Step, in place, the inner world of every live outer cell in region (r0, r1, c0, c1).\n"
"inner: size*size*m*m bytes (C order), macro: size*size bytes. birth / survive: rule bit\n"
"masks. A world that dies out is reseeded at density threshold/256.");

static PyObject *step_inner(PyObject *self, PyObject *args)
{
    PyObject *inner_obj, *macro_obj;
    Py_ssize_t size, m, r0, r1, c0, c1;
    unsigned int birth, survive, threshold;
    if (!PyArg_ParseTuple(args, "OOnn(nnnn)III", &inner_obj, &macro_obj, &size, &m,
                          &r0, &r1, &c0, &c1, &birth, &survive, &threshold))
        return NULL;
    if (m < 1 || m > MAX_M || size < 1) {
        PyErr_SetString(PyExc_ValueError, "bad size or inner size");
        return NULL;
    }
    Py_buffer inner, macro;
    if (get_buffer(inner_obj, &inner, 1, size * size * m * m, "inner") < 0)
        return NULL;
    if (get_buffer(macro_obj, &macro, 0, size * size, "macro") < 0) {
        PyBuffer_Release(&inner);
        return NULL;
    }
    if (check_region(size, &r0, &r1, &c0, &c1)) {
        uint8_t tmp[MAX_M * MAX_M];
        const uint8_t *alive = (const uint8_t *)macro.buf;
        uint8_t *worlds = (uint8_t *)inner.buf;
        Py_ssize_t mm = m * m;
        Py_BEGIN_ALLOW_THREADS
        for (Py_ssize_t r = r0; r < r1; r++)
            for (Py_ssize_t c = c0; c < c1; c++) {
                if (!alive[r * size + c])
                    continue;
                uint8_t *w = worlds + (r * size + c) * mm;
                if (step_world(w, tmp, (int)m, birth, survive) == 0)
                    random_cells(w, mm, threshold);  /* live cells never look empty */
            }
        Py_END_ALLOW_THREADS
    }
    PyBuffer_Release(&inner);
    PyBuffer_Release(&macro);
    Py_RETURN_NONE;
}

PyDoc_STRVAR(inner_pixels_doc,
"inner_pixels(out, rgba, inner, size, m, region) -> (width, height)\n"
"\n"
"Write the inner worlds of region (r0, r1, c0, c1) into out as one tightly packed BGRA\n"
"image, a pixel per inner cell: each takes its outer cell's colour, and its alpha when\n"
"alive (0 when dead). rgba: size*size*4 bytes (RGBA). out: width*height*4 bytes.");

static PyObject *inner_pixels(PyObject *self, PyObject *args)
{
    PyObject *out_obj, *rgba_obj, *inner_obj;
    Py_ssize_t size, m, r0, r1, c0, c1;
    if (!PyArg_ParseTuple(args, "OOOnn(nnnn)", &out_obj, &rgba_obj, &inner_obj, &size, &m,
                          &r0, &r1, &c0, &c1))
        return NULL;
    if (m < 1 || size < 1) {
        PyErr_SetString(PyExc_ValueError, "bad size or inner size");
        return NULL;
    }
    if (!check_region(size, &r0, &r1, &c0, &c1))
        return Py_BuildValue("(nn)", (Py_ssize_t)0, (Py_ssize_t)0);
    Py_ssize_t width = (c1 - c0) * m, height = (r1 - r0) * m;
    Py_buffer out, rgba, inner;
    if (get_buffer(out_obj, &out, 1, width * height * 4, "out") < 0)
        return NULL;
    if (get_buffer(rgba_obj, &rgba, 0, size * size * 4, "rgba") < 0) {
        PyBuffer_Release(&out);
        return NULL;
    }
    if (get_buffer(inner_obj, &inner, 0, size * size * m * m, "inner") < 0) {
        PyBuffer_Release(&out);
        PyBuffer_Release(&rgba);
        return NULL;
    }
    const uint8_t *look = (const uint8_t *)rgba.buf, *bits = (const uint8_t *)inner.buf;
    uint8_t *px = (uint8_t *)out.buf;
    Py_ssize_t mm = m * m;
    Py_BEGIN_ALLOW_THREADS
    for (Py_ssize_t r = r0; r < r1; r++)
        for (Py_ssize_t i = 0; i < m; i++) {        /* one row of pixels */
            uint8_t *dst = px + ((r - r0) * m + i) * width * 4;
            for (Py_ssize_t c = c0; c < c1; c++) {
                const uint8_t *col = look + (r * size + c) * 4;
                const uint8_t *src = bits + (r * size + c) * mm + i * m;
                for (Py_ssize_t j = 0; j < m; j++, dst += 4) {
                    dst[0] = col[2];  /* BGRA: SDL's ARGB8888, the textures' own */
                    dst[1] = col[1];  /* format, so updates need no conversion */
                    dst[2] = col[0];
                    dst[3] = src[j] ? col[3] : 0;
                }
            }
        }
    Py_END_ALLOW_THREADS
    PyBuffer_Release(&out);
    PyBuffer_Release(&rgba);
    PyBuffer_Release(&inner);
    return Py_BuildValue("(nn)", width, height);
}

PyDoc_STRVAR(inherit_inner_doc,
"inherit_inner(inner, old, born, size, m, wrap, threshold, flip)\n"
"\n"
"Every newborn outer cell (born[r, c] != 0) copies the inner world of one live neighbour in\n"
"old (picked in a random direction), then each of its cells flips with chance flip/65536.\n"
"With no live neighbour it gets a random world at density threshold/256. In place.\n"
"inner: size*size*m*m bytes, old / born: size*size bytes.");

static const int OFFSETS[8][2] = {{-1, -1}, {-1, 0}, {-1, 1}, {0, -1}, {0, 1}, {1, -1}, {1, 0}, {1, 1}};

static PyObject *inherit_inner(PyObject *self, PyObject *args)
{
    PyObject *inner_obj, *old_obj, *born_obj;
    Py_ssize_t size, m;
    int wrap;
    unsigned int threshold, flip;
    if (!PyArg_ParseTuple(args, "OOOnnpII", &inner_obj, &old_obj, &born_obj, &size, &m, &wrap,
                          &threshold, &flip))
        return NULL;
    if (m < 1 || size < 1) {
        PyErr_SetString(PyExc_ValueError, "bad size or inner size");
        return NULL;
    }
    Py_buffer inner, old, born;
    if (get_buffer(inner_obj, &inner, 1, size * size * m * m, "inner") < 0)
        return NULL;
    if (get_buffer(old_obj, &old, 0, size * size, "old") < 0) {
        PyBuffer_Release(&inner);
        return NULL;
    }
    if (get_buffer(born_obj, &born, 0, size * size, "born") < 0) {
        PyBuffer_Release(&inner);
        PyBuffer_Release(&old);
        return NULL;
    }
    uint8_t *worlds = (uint8_t *)inner.buf;
    const uint8_t *was = (const uint8_t *)old.buf, *new_ = (const uint8_t *)born.buf;
    Py_ssize_t mm = m * m;
    Py_BEGIN_ALLOW_THREADS
    for (Py_ssize_t r = 0; r < size; r++)
        for (Py_ssize_t c = 0; c < size; c++) {
            if (!new_[r * size + c])
                continue;
            /* A random order of the 8 directions (Fisher-Yates), so lineages don't all drift
             * the same way. */
            int order[8] = {0, 1, 2, 3, 4, 5, 6, 7};
            uint64_t bits = next_rand();
            for (int k = 7; k > 0; k--, bits >>= 4) {
                int j = (int)((bits & 0xF) % (uint64_t)(k + 1)), t = order[k];
                order[k] = order[j];
                order[j] = t;
            }
            const uint8_t *parent = NULL;
            for (int k = 0; k < 8 && !parent; k++) {
                Py_ssize_t pr = r + OFFSETS[order[k]][0], pc = c + OFFSETS[order[k]][1];
                if (wrap) {
                    pr = (pr + size) % size;
                    pc = (pc + size) % size;
                } else if (pr < 0 || pr >= size || pc < 0 || pc >= size) {
                    continue;
                }
                if (was[pr * size + pc])
                    parent = worlds + (pr * size + pc) * mm;
            }
            /* A newborn was dead in `old` and a parent alive, so a newborn is never another's
             * parent: copying in place is safe. */
            uint8_t *w = worlds + (r * size + c) * mm;
            if (parent == NULL) {
                random_cells(w, mm, threshold);
                continue;
            }
            memcpy(w, parent, (size_t)mm);
            for (Py_ssize_t i = 0; i < mm; i += 4) {  /* mutations: 4 cells per random number */
                uint64_t rr = next_rand();
                for (int k = 0; k < 4 && i + k < mm; k++, rr >>= 16)
                    if ((rr & 0xFFFF) < flip)
                        w[i + k] ^= 1;
            }
        }
    Py_END_ALLOW_THREADS
    PyBuffer_Release(&inner);
    PyBuffer_Release(&old);
    PyBuffer_Release(&born);
    Py_RETURN_NONE;
}

static PyObject *seed(PyObject *self, PyObject *arg)
{
    unsigned long long s = PyLong_AsUnsignedLongLongMask(arg);
    if (PyErr_Occurred())
        return NULL;
    rng = s ? s : 0x9E3779B97F4A7C15ULL;  /* xorshift must never be 0 */
    Py_RETURN_NONE;
}

static PyMethodDef methods[] = {
    {"step_inner", step_inner, METH_VARARGS, step_inner_doc},
    {"inner_pixels", inner_pixels, METH_VARARGS, inner_pixels_doc},
    {"inherit_inner", inherit_inner, METH_VARARGS, inherit_inner_doc},
    {"seed", seed, METH_O, "seed(n): seed the random numbers used to reseed empty worlds."},
    {NULL, NULL, 0, NULL},
};

static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT, "_core",
    "In-place C versions of the per-frame inner-world work (see _core.c).", -1, methods,
};

PyMODINIT_FUNC PyInit__core(void)
{
    rng ^= (uint64_t)time(NULL) * 0xBF58476D1CE4E5B9ULL ^ (uint64_t)(uintptr_t)&module;
    if (!rng)
        rng = 0x9E3779B97F4A7C15ULL;
    return PyModule_Create(&module);
}
