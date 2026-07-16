/*-----------------------------------------------------------------------*/
/* STREAM benchmark (John D. McCalpin), condensed/standard variant.       */
/* Measures sustainable memory bandwidth (MB/s) for Copy/Scale/Add/Triad. */
/* Compile: gcc -O3 -fopenmp -DSTREAM_ARRAY_SIZE=80000000 -DNTIMES=20     */
/*-----------------------------------------------------------------------*/
#include <stdio.h>
#include <math.h>
#include <float.h>
#include <limits.h>
#include <sys/time.h>
#include <stdlib.h>
#ifdef _OPENMP
#include <omp.h>
#endif

#ifndef STREAM_ARRAY_SIZE
#define STREAM_ARRAY_SIZE 80000000
#endif
#ifndef NTIMES
#define NTIMES 20
#endif
#ifndef OFFSET
#define OFFSET 0
#endif

#define STREAM_TYPE double

static STREAM_TYPE a[STREAM_ARRAY_SIZE+OFFSET],
                   b[STREAM_ARRAY_SIZE+OFFSET],
                   c[STREAM_ARRAY_SIZE+OFFSET];

static double avgtime[4] = {0}, maxtime[4] = {0},
       mintime[4] = {FLT_MAX,FLT_MAX,FLT_MAX,FLT_MAX};

static char *label[4] = {"Copy:      ", "Scale:     ",
    "Add:       ", "Triad:     "};

static double bytes[4] = {
    2 * sizeof(STREAM_TYPE) * STREAM_ARRAY_SIZE,
    2 * sizeof(STREAM_TYPE) * STREAM_ARRAY_SIZE,
    3 * sizeof(STREAM_TYPE) * STREAM_ARRAY_SIZE,
    3 * sizeof(STREAM_TYPE) * STREAM_ARRAY_SIZE
    };

static double mysecond(void)
{
    struct timeval tp;
    gettimeofday(&tp,NULL);
    return ((double) tp.tv_sec + (double) tp.tv_usec * 1.e-6);
}

int main(void)
{
    int quantum;
    int BytesPerWord = sizeof(STREAM_TYPE);
    ssize_t j;
    int k;
    STREAM_TYPE scalar;
    double t, times[4][NTIMES];

    printf("-------------------------------------------------------------\n");
    printf("STREAM version (condensed McCalpin)\n");
    printf("-------------------------------------------------------------\n");
    printf("Array size = %llu (elements), Offset = %d (elements)\n",
        (unsigned long long) STREAM_ARRAY_SIZE, OFFSET);
    printf("Memory per array = %.1f MiB (= %.1f GiB).\n",
        BytesPerWord * ((double) STREAM_ARRAY_SIZE / 1024.0/1024.0),
        BytesPerWord * ((double) STREAM_ARRAY_SIZE / 1024.0/1024.0/1024.0));
    printf("Total memory required = %.1f GiB.\n",
        (3.0 * BytesPerWord) * ((double) STREAM_ARRAY_SIZE / 1024.0/1024.0/1024.0));
    printf("Each kernel will be executed %d times.\n", NTIMES);
#ifdef _OPENMP
#pragma omp parallel
    {
#pragma omp master
        printf("Number of Threads requested = %d\n", omp_get_num_threads());
    }
#endif

#pragma omp parallel for
    for (j=0; j<STREAM_ARRAY_SIZE; j++) {
        a[j] = 1.0; b[j] = 2.0; c[j] = 0.0;
    }

    scalar = 3.0;
    for (k=0; k<NTIMES; k++)
    {
        times[0][k] = mysecond();
#pragma omp parallel for
        for (j=0; j<STREAM_ARRAY_SIZE; j++) c[j] = a[j];
        times[0][k] = mysecond() - times[0][k];

        times[1][k] = mysecond();
#pragma omp parallel for
        for (j=0; j<STREAM_ARRAY_SIZE; j++) b[j] = scalar*c[j];
        times[1][k] = mysecond() - times[1][k];

        times[2][k] = mysecond();
#pragma omp parallel for
        for (j=0; j<STREAM_ARRAY_SIZE; j++) c[j] = a[j]+b[j];
        times[2][k] = mysecond() - times[2][k];

        times[3][k] = mysecond();
#pragma omp parallel for
        for (j=0; j<STREAM_ARRAY_SIZE; j++) a[j] = b[j]+scalar*c[j];
        times[3][k] = mysecond() - times[3][k];
    }

    /* skip first iteration */
    for (k=1; k<NTIMES; k++)
    {
        for (j=0; j<4; j++)
        {
            avgtime[j] = avgtime[j] + times[j][k];
            mintime[j] = (mintime[j] < times[j][k]) ? mintime[j] : times[j][k];
            maxtime[j] = (maxtime[j] > times[j][k]) ? maxtime[j] : times[j][k];
        }
    }

    printf("Function    Best Rate MB/s  Avg time     Min time     Max time\n");
    for (j=0; j<4; j++) {
        avgtime[j] = avgtime[j]/(double)(NTIMES-1);
        printf("%s%12.1f  %11.6f  %11.6f  %11.6f\n", label[j],
            1.0E-06 * bytes[j]/mintime[j],
            avgtime[j], mintime[j], maxtime[j]);
    }
    printf("-------------------------------------------------------------\n");
    /* machine-parseable line, GB/s (1e9) to match STREAM MB/s(1e6)/1000 */
    printf("TRIAD_GBS %.3f\n", (1.0E-09 * bytes[3]/mintime[3]));
    return 0;
}
