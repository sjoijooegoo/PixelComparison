import { describe, expect, it } from 'vitest'
import { readMapBuildArtifact } from './mapBuildManifest'

const file = (value) => ({ text: async () => value })

describe('map build manifest artifact', () => {
  it('兼容反斜杠路径并读取声明的格式与 JSON', async () => {
    const manifest = {
      artifacts: {
        map_build_data: {
          path: 'Artifacts\\MapBuildData\\map_build_data.json',
          format: 'map-build-data/v2',
        },
      },
    }
    const files = new Map([
      ['Package/Artifacts/MapBuildData/map_build_data.json', file('{"registries":[]}')],
    ])

    await expect(readMapBuildArtifact(manifest, files, 'Package/')).resolves.toEqual({
      data: { registries: [] },
      format: 'map-build-data/v2',
      missing: '',
    })
  })

  it('旧 manifest 不声明 artifact 时保持可上报', async () => {
    await expect(readMapBuildArtifact({}, new Map())).resolves.toEqual({
      data: null,
      format: null,
      missing: '',
    })
  })

  it('声明但文件缺失时返回明确路径，非法 JSON 直接阻止误上报', async () => {
    const manifest = { artifacts: { map_build_data: { path: 'Artifacts/map.json' } } }
    await expect(readMapBuildArtifact(manifest, new Map())).resolves.toMatchObject({
      data: null,
      missing: 'Artifacts/map.json',
    })
    await expect(readMapBuildArtifact(
      manifest,
      new Map([['Artifacts/map.json', file('{bad')]]),
    )).rejects.toThrow('烘培数据 JSON 解析失败')
  })

  it('拒绝盘符、根目录和上级目录路径，只允许读取数据包内部文件', async () => {
    const files = new Map([
      ['C:/outside.json', file('{"registries":[{"path":"outside"}]}')],
      ['outside.json', file('{"registries":[{"path":"outside"}]}')],
    ])

    for (const path of ['C:\\outside.json', '/outside.json', '../outside.json']) {
      await expect(readMapBuildArtifact(
        { artifacts: { map_build_data: { path } } },
        files,
      )).resolves.toEqual({
        data: null,
        format: 'map-build-data/v2',
        missing: path,
      })
    }
  })

  it('语法正确但根节点不是对象的 JSON 仍拒绝上报', async () => {
    const manifest = { artifacts: { map_build_data: { path: 'Artifacts/map.json' } } }

    await expect(readMapBuildArtifact(
      manifest,
      new Map([['Artifacts/map.json', file('[]')]]),
    )).rejects.toThrow('烘培数据必须是 JSON 对象')
  })
})
